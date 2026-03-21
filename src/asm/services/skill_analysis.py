"""Unified skill analysis service for cloud and local LLM flows."""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, StateGraph

from asm.core import paths
from asm.core.models import (
    SimilarSkillMatch,
    SkillAnalysisArtifact,
    SkillAnalysisRequest,
    SkillAnalysisResponse,
    SkillManifest,
    SkillScorecard,
)
from asm.repo import analysis, config
from asm.services.analysis_feedback import (
    AnalysisFeedbackError,
    analyze_local_analysis_feedback_sync,
    build_skill_improvement_prompt,
)
from asm.services import cloud_analysis, deepwiki, embeddings, llm

CloudAnalysisError = cloud_analysis.CloudAnalysisError


class LocalAnalysisError(RuntimeError):
    """Raised when local OpenAI-backed analysis cannot complete."""


@dataclass
class SkillImprovementLoopResult:
    """Outcome of the LangGraph-backed local improvement loop."""

    attempts: int
    target_score: float
    final_score: float
    reached_target: bool
    artifact_path: Path | None = None
    stop_reason: str = ""


class SkillImprovementLoopState(TypedDict, total=False):
    """State carried through the LangGraph-based skill improvement loop."""

    root: Path
    name: str
    model: str | None
    target_score: float
    max_tries: int
    attempts: int
    final_score: float
    reached_target: bool
    artifact_path: Path | None
    improvement_prompt: str
    stop_reason: str
    # analyzer signals used for gating/research
    trigger_specificity: float
    evidence_grounding: float
    status: str
    recommended_actions: list[str]
    # online evidence research
    decision: str
    search_limit: int
    research_query: str
    research_context: str
    research_repo_full_names: list[str]
    quality_gate_failed: bool
    quality_gate_issues: list[str]


def scorecard_overall_score(scorecard: SkillScorecard) -> float:
    """Collapse the scorecard into one 0-1 score for local improvement loops."""
    weighted_total = (
        scorecard.trigger_specificity
        + scorecard.novelty
        + scorecard.evidence_grounding
        + (1.0 - scorecard.duplication_risk)
    )
    return round(weighted_total / 4.0, 4)


def analyze_skill_cloud(
    root: Path,
    name: str,
    *,
    api_url: str | None = None,
    api_key: str | None = None,
) -> tuple[SkillAnalysisResponse, Path]:
    """Delegate to the managed cloud analyzer and persist the artifact."""
    return cloud_analysis.analyze_skill_cloud(root, name, api_url=api_url, api_key=api_key)


def analyze_skill_local(
    root: Path,
    name: str,
    *,
    model: str | None = None,
) -> tuple[SkillAnalysisResponse, Path]:
    """Run local OpenAI-backed analysis using ASM_LLM_MODEL and OPENAI_API_KEY."""
    request = cloud_analysis.build_skill_analysis_request(root, name, analysis_mode="local-llm")
    similar_skills = _find_local_similar_skills(root, name, request.manifest)
    response = _run_local_llm_analysis(request, similar_skills, model=model)
    artifact = SkillAnalysisArtifact(
        manifest=request.manifest,
        evidence=request.evidence,
        scorecard=response.scorecard,
        embedding_profile=response.embedding_profile,
        snapshot_id=request.manifest.snapshot_id,
        integrity=request.manifest.integrity,
    )
    analysis.save_skill_manifest(root, name, request.manifest)
    artifact_path = analysis.save_skill_analysis_artifact(root, name, artifact)
    return response, artifact_path


def run_local_improvement_graph(
    root: Path,
    name: str,
    *,
    model: str | None = None,
    target_score: float = 0.9,
    max_tries: int = 5,
    on_progress: Callable[[str], None] | None = None,
) -> SkillImprovementLoopResult:
    """Use LangGraph to iterate analyze -> rewrite until the score gate passes."""
    emit = on_progress or (lambda _msg: None)
    graph = _build_local_improvement_graph(emit)
    final_state = graph.invoke(
        {
            "root": root,
            "name": name,
            "model": model,
            "target_score": target_score,
            "max_tries": max_tries,
            "attempts": 0,
            "final_score": 0.0,
            "reached_target": False,
            "artifact_path": None,
            "improvement_prompt": "",
            "stop_reason": "",
            "trigger_specificity": 0.0,
            "evidence_grounding": 0.0,
            "status": "",
            "recommended_actions": [],
            "decision": "rewrite",
            "search_limit": 3,
            "research_query": "",
            "research_context": "",
            "research_repo_full_names": [],
            "quality_gate_failed": False,
            "quality_gate_issues": [],
        }
    )
    return SkillImprovementLoopResult(
        attempts=int(final_state.get("attempts", 0)),
        target_score=target_score,
        final_score=float(final_state.get("final_score", 0.0)),
        reached_target=bool(final_state.get("reached_target", False)),
        artifact_path=final_state.get("artifact_path"),
        stop_reason=str(final_state.get("stop_reason", "")),
    )


def _run_local_llm_analysis(
    request: SkillAnalysisRequest,
    similar_skills: list[SimilarSkillMatch],
    *,
    model: str | None = None,
) -> SkillAnalysisResponse:
    analysis_id = f"local-{uuid.uuid4()}"
    analysis_version = "asm-local-openai-v1"
    embedding_profile = embeddings.current_profile(analysis_mode="local-llm")
    try:
        payload = analyze_local_analysis_feedback_sync(
            request,
            similar_skills,
            analysis_id=analysis_id,
            analysis_version=analysis_version,
            model=model,
        )
    except AnalysisFeedbackError as exc:
        raise LocalAnalysisError(str(exc)) from exc
    recommended_actions = list(payload.recommended_actions)
    scorecard = SkillScorecard(
        skill_name=request.manifest.name,
        analysis_id=analysis_id,
        analysis_version=analysis_version,
        trigger_specificity=float(payload.trigger_specificity),
        novelty=float(payload.novelty),
        evidence_grounding=float(payload.evidence_grounding),
        duplication_risk=float(payload.duplication_risk),
        status=str(payload.status),
        findings=list(payload.findings),
        recommended_actions=recommended_actions,
        improvement_prompt=build_skill_improvement_prompt(
            request.manifest,
            recommended_actions,
            similar_skills,
        ),
        similar_skills=similar_skills,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    return SkillAnalysisResponse(
        analysis_id=analysis_id,
        analysis_version=analysis_version,
        scorecard=scorecard,
        embedding_profile=embedding_profile,
    )


def _build_local_improvement_graph(on_progress: Callable[[str], None]) -> object:
    """Build the LangGraph workflow used by the core skill improvement loop."""
    graph = StateGraph(SkillImprovementLoopState)
    graph.add_node("analyze", lambda state: _analyze_skill_iteration(state, on_progress))
    graph.add_node("decide", lambda state: _decide_after_analysis(state, on_progress))
    graph.add_node("research", lambda state: _research_iteration(state, on_progress))
    graph.add_node("materialize", lambda state: _materialize_research_files(state, on_progress))
    graph.add_node("rewrite", lambda state: _rewrite_skill_iteration(state, on_progress))
    graph.set_entry_point("analyze")
    graph.add_edge("analyze", "decide")
    graph.add_conditional_edges(
        "decide",
        _route_after_decide,
        {
            "research": "research",
            "rewrite": "rewrite",
            "finish": END,
        },
    )
    graph.add_edge("research", "materialize")
    graph.add_edge("materialize", "rewrite")
    graph.add_conditional_edges(
        "rewrite",
        _route_after_rewrite,
        {
            "analyze": "analyze",
            "finish": END,
        },
    )
    return graph.compile()


def _analyze_skill_iteration(
    state: SkillImprovementLoopState,
    on_progress: Callable[[str], None],
) -> SkillImprovementLoopState:
    """Run one analysis pass and update loop state."""
    attempts = int(state.get("attempts", 0)) + 1
    skill_dir = paths.skills_dir(state["root"]) / state["name"]
    try:
        response, artifact_path = analyze_skill_local(
            state["root"],
            state["name"],
            model=state.get("model"),
        )
    except LocalAnalysisError as exc:
        on_progress(f"Analysis step failed: {exc}; stopping loop with current draft.")
        return {
            **state,
            "attempts": attempts,
            "final_score": 0.0,
            "artifact_path": None,
            "improvement_prompt": "",
            "reached_target": False,
            "stop_reason": "analysis_failed",
        }

    final_score = scorecard_overall_score(response.scorecard)
    on_progress(
        f"Loop {attempts}/{state['max_tries']}: score {final_score:.2f} "
        f"(target {state['target_score']:.2f})"
    )
    improvement_prompt = response.scorecard.improvement_prompt.strip()
    quality_gate_issues = _evaluate_support_file_quality(skill_dir)
    quality_gate_failed = bool(quality_gate_issues)
    if quality_gate_failed:
        on_progress(f"Quality gate failed with {len(quality_gate_issues)} issue(s).")
        quality_block = "\n".join(f"- {issue}" for issue in quality_gate_issues[:10])
        improvement_prompt = (
            f"{improvement_prompt}\n\n"
            "Support-file quality gate failures:\n"
            f"{quality_block}"
        ).strip()
    reached_target = final_score >= float(state["target_score"]) and not quality_gate_failed

    if reached_target:
        stop_reason = "reached_target"
    elif quality_gate_failed and attempts >= int(state["max_tries"]):
        stop_reason = "quality_gate_failed"
    elif attempts >= int(state["max_tries"]):
        stop_reason = "max_tries"
    elif not improvement_prompt:
        stop_reason = "missing_improvement_prompt"
    else:
        stop_reason = ""

    return {
        **state,
        "attempts": attempts,
        "final_score": final_score,
        "artifact_path": artifact_path,
        "improvement_prompt": improvement_prompt,
        "reached_target": reached_target,
        "stop_reason": stop_reason,
        "trigger_specificity": float(response.scorecard.trigger_specificity),
        "evidence_grounding": float(response.scorecard.evidence_grounding),
        "status": str(response.scorecard.status),
        "recommended_actions": list(response.scorecard.recommended_actions),
        "quality_gate_failed": quality_gate_failed,
        "quality_gate_issues": quality_gate_issues,
    }


def _decide_after_analysis(
    state: SkillImprovementLoopState,
    on_progress: Callable[[str], None],
) -> SkillImprovementLoopState:
    """Route to finish, research, or rewrite based on analyzer signals."""
    if state.get("stop_reason"):
        decision = "finish"
    else:
        # Conservative defaults: if evidence grounding or trigger routing are weak,
        # fetch better sources before rewriting.
        evidence_threshold = 0.75
        trigger_threshold = 0.7
        low_evidence = float(state.get("evidence_grounding", 0.0)) < evidence_threshold
        low_trigger = float(state.get("trigger_specificity", 0.0)) < trigger_threshold
        needs_research = (
            low_evidence
            or low_trigger
            or state.get("status") == "insufficient_evidence"
        )
        decision = "research" if needs_research else "rewrite"

    on_progress(f"Decision after analysis: {decision}")
    return {**state, "decision": decision}


def _route_after_decide(state: SkillImprovementLoopState) -> str:
    """Return the next node key based on the decide node."""
    return str(state.get("decision") or "rewrite")


def _build_research_query(state: SkillImprovementLoopState) -> str:
    """Build a compact research query from the analyzer signals."""
    name = str(state.get("name") or "")
    actions = list(state.get("recommended_actions") or [])
    if actions:
        parts: list[str] = []
        for action in actions[:3]:
            s = str(action)
            s = s.replace("\n", " ").replace("\r", " ")
            # Remove some common prompt-ish fragments that make GitHub search noisy.
            s = re.sub(r"\b(e\.g\.|e\.g|for example)\b.*", "", s, flags=re.IGNORECASE).strip()
            s = re.sub(r"\b(provide|include|embed|replace|populate)\b.*", "", s, flags=re.IGNORECASE).strip()
            s = re.sub(r"\s+", " ", s).strip()
            if not s:
                continue
            parts.append(s[:80])
        snippet = " ".join(parts).strip()
        query = f"{name} {snippet}".strip()
        # Keep query short for GitHub search stability.
        return query[:200].strip()
    return name[:200].strip()


def _research_iteration(
    state: SkillImprovementLoopState,
    on_progress: Callable[[str], None],
) -> SkillImprovementLoopState:
    """Fetch online evidence using DeepWiki/GitHub context."""
    query = _build_research_query(state)
    limit = int(state.get("search_limit", 3))
    on_progress(f"Researching evidence (limit={limit}) for query: {query!r}")
    try:
        context, matches = deepwiki.fetch_search_context(query, limit=limit)
        repo_names = [m.full_name for m in matches]
        return {
            **state,
            "research_query": query,
            "research_context": context,
            "research_repo_full_names": repo_names,
        }
    except Exception as exc:
        # Fail-soft: keep the loop alive and rewrite using existing evidence.
        on_progress(f"Research step failed ({exc}); continuing with existing evidence.")
        return {
            **state,
            "research_query": query,
            "research_context": "",
            "research_repo_full_names": [],
        }


def _materialize_research_files(
    state: SkillImprovementLoopState,
    on_progress: Callable[[str], None],
) -> SkillImprovementLoopState:
    """Write fetched evidence into `references/` for deterministic rewrite inputs."""
    skill_dir = paths.skills_dir(state["root"]) / state["name"]
    references_dir = skill_dir / "references"
    references_dir.mkdir(parents=True, exist_ok=True)

    attempt = int(state.get("attempts", 1))
    out_path = references_dir / f"research-iteration-{attempt}.md"

    query = state.get("research_query", "")
    repo_names = state.get("research_repo_full_names", [])
    context = state.get("research_context", "")

    on_progress(f"Materializing research evidence into {out_path.as_posix()}")
    out_path.write_text(
        "\n".join(
            [
                "# Research Evidence (iteration)",
                "",
                f"- attempt: {attempt}",
                f"- query: {query}",
                f"- sources: {', '.join(repo_names) if repo_names else '(none)'}",
                "",
                "## Evidence context (DeepWiki/GitHub)",
                "",
                context or "_No evidence context returned (fail-soft fallback).",
                "",
            ]
        ),
        encoding="utf-8",
    )

    return state


def _rewrite_skill_iteration(
    state: SkillImprovementLoopState,
    on_progress: Callable[[str], None],
) -> SkillImprovementLoopState:
    """Rewrite the skill package using the analyzer improvement prompt."""
    skill_dir = paths.skills_dir(state["root"]) / state["name"]
    supporting_files = _supporting_skill_files(skill_dir)
    on_progress("Rewriting skill from analyzer feedback…")
    try:
        revised_desc, revised_body = llm.revise_skill_content(
            state["name"],
            (skill_dir / "SKILL.md").read_text(encoding="utf-8"),
            state.get("improvement_prompt", ""),
            model=state.get("model"),
            supporting_files=supporting_files,
        )
    except llm.LLMError as exc:
        on_progress(f"Rewrite step failed: {exc}; stopping loop with current draft.")
        return {
            **state,
            "stop_reason": "rewrite_failed",
        }

    (skill_dir / "SKILL.md").write_text(
        _render_skill_md(state["name"], revised_desc, revised_body),
        encoding="utf-8",
    )

    # Materialize any missing support files referenced by the rewritten SKILL.md.
    # This turns the builder into a true "materialize evidence/examples" loop,
    # not just "mention files in SKILL.md".
    skill_md_text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    niche_examples = _extract_niche_examples(skill_md_text)
    referenced_paths = _extract_referenced_support_paths(skill_md_text)
    created = _materialize_missing_support_files(
        skill_dir,
        referenced_paths,
        niche_examples=niche_examples,
        skill_name=state["name"],
        current_skill_md=skill_md_text,
        model=state.get("model"),
        on_progress=on_progress,
    )
    if created:
        on_progress(f"Materialized {created} missing support file(s) from SKILL.md.")
    return state


def _route_after_analysis(state: SkillImprovementLoopState) -> str:
    """Decide whether the graph should finish or continue rewriting."""
    if state.get("stop_reason"):
        return "finish"
    return "rewrite"


def _route_after_rewrite(state: SkillImprovementLoopState) -> str:
    """Stop on rewrite failure, otherwise continue to another analysis pass."""
    if state.get("stop_reason"):
        return "finish"
    return "analyze"


def _supporting_skill_files(skill_dir: Path) -> list[str]:
    """List support files available for rewrite prompts."""
    files: list[str] = []
    for folder_name in ("references", "examples", "scripts", "assets"):
        folder = skill_dir / folder_name
        if not folder.exists():
            continue
        for file_path in sorted(folder.rglob("*")):
            if file_path.is_file():
                files.append(file_path.relative_to(skill_dir).as_posix())
    return files


def _extract_niche_examples(skill_md_text: str) -> str:
    """Extract the body text under `## Niche Examples` (if present)."""
    match = re.search(
        r"^##\s+Niche Examples\s*$\n(?P<body>.*?)(?=^##\s+|\Z)",
        skill_md_text,
        flags=re.MULTILINE | re.DOTALL,
    )
    return match.group("body").strip() if match else ""


def _extract_referenced_support_paths(skill_md_text: str) -> list[str]:
    """Find support-file paths mentioned in SKILL.md (references/examples/scripts/assets)."""
    # Matches things like:
    # - `references/foo.md`
    # - examples/cdp-attach.js
    # - scripts/run_demo.sh
    pattern = r"(?:references|examples|scripts|assets)/[A-Za-z0-9._/\-]+(?:\.[A-Za-z0-9]+)?"
    raw_paths = re.findall(pattern, skill_md_text)
    cleaned: list[str] = []
    seen: set[str] = set()
    for p in raw_paths:
        p = p.strip().strip("`")
        if p.endswith("/"):
            continue
        # Normalize: drop trailing punctuation that often appears in markdown lists.
        p = p.rstrip(").,:;")
        if not p or p in seen:
            continue
        seen.add(p)
        cleaned.append(p)
    return cleaned


_PLACEHOLDER_MARKERS = (
    "materialized by asm",
    "generated by asm as a minimal",
    "edit/extend this file as you refine the skill",
    "no `## niche examples` section found",
    "generated minimal artifact",
    "todo: implement",
    "placeholder",
)


def _evaluate_support_file_quality(skill_dir: Path) -> list[str]:
    """Return quality-gate issues for materialized support files."""
    issues: list[str] = []
    support_paths = _supporting_skill_files(skill_dir)
    if not support_paths:
        return ["No support files exist under references/, examples/, scripts/, or assets/."]

    normalized_by_path: list[tuple[str, str]] = []
    for rel_path in support_paths:
        path = skill_dir / rel_path
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            issues.append(f"{rel_path}: could not be read for quality inspection.")
            continue

        lower = text.lower()
        matched_markers = [marker for marker in _PLACEHOLDER_MARKERS if marker in lower]
        if matched_markers:
            issues.append(
                f"{rel_path}: contains placeholder/scaffold markers ({', '.join(matched_markers[:3])})."
            )

        lines = [line for line in text.splitlines() if line.strip()]
        if rel_path.startswith("examples/") and len(lines) < 12:
            issues.append(f"{rel_path}: example file is too thin; add concrete steps, commands, and outputs.")

        if rel_path.startswith("scripts/"):
            code_lines = [
                line.strip()
                for line in lines
                if not line.strip().startswith(("#", "//", "/*", "*", "*/"))
            ]
            if len(code_lines) < 5:
                issues.append(f"{rel_path}: script lacks enough executable logic to be considered runnable.")

        normalized_by_path.append((rel_path, _normalize_support_file_text(text)))

    for idx, (left_path, left_text) in enumerate(normalized_by_path):
        if len(left_text) < 80:
            continue
        for right_path, right_text in normalized_by_path[idx + 1 :]:
            if len(right_text) < 80:
                continue
            similarity = SequenceMatcher(a=left_text, b=right_text).ratio()
            if similarity >= 0.9:
                issues.append(
                    f"{left_path} and {right_path}: content is too similar ({similarity:.2f}); generate more specialized files."
                )

    return issues


def _normalize_support_file_text(text: str) -> str:
    """Normalize support-file text before duplicate detection."""
    lines: list[str] = []
    for idx, line in enumerate(text.splitlines()):
        stripped = line.strip().lower()
        if idx == 0 and stripped.startswith("# "):
            continue
        if not stripped:
            continue
        lines.append(stripped)
    return "\n".join(lines)


def _materialize_missing_support_files(
    skill_dir: Path,
    referenced_paths: list[str],
    *,
    niche_examples: str,
    skill_name: str,
    current_skill_md: str,
    model: str | None,
    on_progress: Callable[[str], None],
    max_files: int = 5,
) -> int:
    """Create missing support files referenced in SKILL.md.

    Important: materialized content must be *non-placeholder* and should
    avoid "TODO" or "Materialized by ASM" markers, otherwise the analyzer
    can incorrectly treat it as strong evidence while it isn't runnable.
    """
    created = 0
    existing_supporting_files = _supporting_skill_files(skill_dir)
    for rel_path in referenced_paths[:max_files]:
        target = skill_dir / rel_path
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        content = _fallback_materialized_support_content(rel_path, niche_examples=niche_examples)
        try:
            content = llm.generate_support_file_content(
                skill_name,
                current_skill_md,
                rel_path,
                niche_examples=niche_examples,
                model=model,
                supporting_files=existing_supporting_files,
            )
        except Exception:
            pass
        target.write_text(content, encoding="utf-8")
        on_progress(f"Materialized support file: {rel_path}")
        created += 1
    return created


def _fallback_materialized_support_content(rel_path: str, *, niche_examples: str) -> str:
    """Fallback content when support-file LLM generation fails."""
    target = Path(rel_path)
    suffix = target.suffix.lower()
    if suffix in {".md", ".txt", ".markdown"}:
        title = target.stem.replace("-", " ").title()
        examples_block = niche_examples or "(No `## Niche Examples` section found in SKILL.md.)"
        return "\n".join(
            [
                f"# {title}",
                "",
                "Generated by ASM as a minimal, evidence-backed usage file.",
                "Edit/extend this file as you refine the skill.",
                "",
                "## Niche Examples",
                "",
                examples_block,
                "",
                "## Quick Start",
                "",
                "1) Locate the main entrypoint for this skill.",
                "2) Follow the niche example narrative for the exact workflow.",
                "3) Verify outputs by checking the referenced artifact paths.",
                "",
            ]
        )

    examples_block = niche_examples or "(No `## Niche Examples` section found in SKILL.md.)"
    if suffix == ".py":
        return "\n".join(
            [
                "#!/usr/bin/env python3",
                "\"\"\"Minimal runnable helper for replay/trace workflows.\"\"\"",
                "",
                "from __future__ import annotations",
                "",
                "import argparse",
                "import json",
                "from pathlib import Path",
                "",
                "",
                "def main():",
                "    ap = argparse.ArgumentParser()",
                "    ap.add_argument('--trace', required=True, help='CDP trace JSON file')",
                "    ap.add_argument('--out-dir', required=False, default='.', help='Output directory')",
                "    args = ap.parse_args()",
                "    trace_path = Path(args.trace)",
                "    out_dir = Path(args.out_dir)",
                "    out_dir.mkdir(parents=True, exist_ok=True)",
                "    data = json.loads(trace_path.read_text(encoding='utf-8'))",
                "    steps = len(data) if isinstance(data, list) else 1",
                "    out_path = out_dir / 'replay_summary.json'",
                "    out_path.write_text(json.dumps({'trace_path': trace_path.as_posix(), 'step_count_estimate': steps}, indent=2), encoding='utf-8')",
                "    print(f'Wrote {out_path.as_posix()}')",
                "",
                "",
                "if __name__ == '__main__':",
                "    main()",
                "",
            ]
        )
    if suffix == ".sh":
        return "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                "",
                "scenario=\"\"",
                "out_dir=\".\"",
                "",
                "while [[ $# -gt 0 ]]; do",
                "  case \"$1\" in",
                "    --scenario) scenario=\"$2\"; shift 2 ;;",
                "    --out) out_dir=\"$2\"; shift 2 ;;",
                "    *) echo \"Unknown arg: $1\"; exit 2 ;;",
                "  esac",
                "done",
                "",
                "if [[ -z \"$scenario\" ]]; then",
                "  echo \"--scenario is required\"",
                "  exit 2",
                "fi",
                "",
                "mkdir -p \"$out_dir/artifacts\"",
                "echo \"{\\\"scenario\\\": \\\"$scenario\\\"}\" > \"$out_dir/artifacts/trace.json\"",
                "echo \"<html><body>placeholder</body></html>\" > \"$out_dir/artifacts/dom.html\"",
                "echo \"Wrote artifacts to $out_dir/artifacts\"",
                "",
            ]
        )
    return "\n".join(
        [
            "#!/usr/bin/env sh",
            "echo \"Generated minimal artifact.\"",
            *[f"# {line}" for line in examples_block.splitlines()[:10]],
            "",
        ]
    )


def _render_skill_md(name: str, description: str, body: str) -> str:
    """Render the full SKILL.md text from rewritten LLM output."""
    return "\n".join(
        [
            "---",
            f"name: {name}",
            f"description: {description}",
            "---",
            "",
            body,
            "",
        ]
    )
def _find_local_similar_skills(root: Path, current_name: str, manifest: SkillManifest) -> list[SimilarSkillMatch]:
    cfg = config.load(root / "asm.toml")
    if not cfg.skills:
        return []

    current_text = _manifest_similarity_text(manifest)
    current_vector = embeddings.embed(current_text)
    matches: list[SimilarSkillMatch] = []
    for name in sorted(cfg.skills):
        if name == current_name:
            continue
        try:
            other_manifest = cloud_analysis.build_skill_manifest(root, name)
        except Exception:
            continue
        similarity = embeddings.cosine_similarity(
            current_vector,
            embeddings.embed(_manifest_similarity_text(other_manifest)),
        )
        matches.append(SimilarSkillMatch(name=name, similarity=round(similarity, 4)))
    matches.sort(key=lambda item: item.similarity, reverse=True)
    return matches[:3]


def _manifest_similarity_text(manifest: SkillManifest) -> str:
    inventory = manifest.resource_inventory
    return " ".join(
        [
            manifest.name,
            manifest.description,
            " ".join(manifest.trigger_phrases),
            " ".join(inventory.references.files),
            " ".join(inventory.scripts.files),
            " ".join(inventory.examples.files),
            " ".join(inventory.assets.files),
        ]
    )


