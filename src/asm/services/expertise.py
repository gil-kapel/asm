"""Expertise service — bundle skills into task-oriented domains.

Phase A: create expertise from explicit skill list or LLM-suggested selection.
Phase B: suggest/auto commands for autonomous agent matching.
"""

from __future__ import annotations

import json
from pathlib import Path

from asm.core import paths
from asm.core.models import (
    AsmConfig,
    ExpertiseRef,
    RoutingBenchmarkCase,
    RoutingCaseResult,
    RoutingEvaluationReport,
    SkillPolicy,
)
from asm.repo import config
from asm.services import embeddings

_ADVANCED_SKILL_CLASSIFICATION: dict[str, str] = {
    "sqlmodel-database": "Advanced async session safety, relationship modeling, and migration-safe schemas.",
    "sql": "Advanced query optimization and schema-level decision patterns.",
    "react-expert": "Advanced React architecture, performance boundaries, and modern component strategy.",
    "shadcn-ui": "Advanced component system composition and customization patterns.",
    "llm-structured-output": "Advanced deterministic schema-driven LLM output integration.",
    "skill-development": "Advanced skill-system design and reusable blueprint authoring.",
    "python-packaging": "Advanced packaging and release workflows for reusable Python tooling.",
    "python-testing": "Advanced testing strategy and reliability patterns beyond basic assertions.",
    "zendriver": "Advanced browser automation and non-trivial interaction orchestration.",
}


def create_expertise(
    name: str,
    description: str,
    skill_names: list[str],
    root: Path,
) -> Path:
    """Create an expertise bundle from an explicit list of skills.

    Writes .asm/expertises/<name>/index.md and updates asm.toml.
    Returns the path to the created index.md.
    """
    cfg_path = root / paths.ASM_TOML
    cfg = config.load(cfg_path)

    missing = [s for s in skill_names if s not in cfg.skills]
    if missing:
        raise ValueError(f"Skills not installed: {', '.join(missing)}")

    expertise_dir = paths.asm_dir(root) / "expertises" / name
    expertise_dir.mkdir(parents=True, exist_ok=True)

    skill_policies = _default_skill_policies(skill_names)
    ref = ExpertiseRef(
        name=name,
        description=description,
        skills=list(skill_names),
        intent_tags=[name.replace("-", " "), "expertise routing"],
        task_signals=[description],
        confidence_hint="Use when task signals strongly match this domain vocabulary.",
        selection_rubric=[
            "Match at least one task signal before selecting this expertise.",
            "Load required skills first; then add advanced optional skills.",
            "Only use fallback skills if advanced optional skills do not fit.",
        ],
        prefer_advanced=True,
        skill_policies=skill_policies,
    )

    index_md = _render_index(ref, cfg)
    index_path = expertise_dir / "index.md"
    index_path.write_text(index_md, encoding="utf-8")

    relationships_md = _render_relationships(ref)
    (expertise_dir / "relationships.md").write_text(relationships_md, encoding="utf-8")

    cfg.expertises[name] = ref
    config.save(cfg, cfg_path)

    return index_path


def create_expertise_auto(
    name: str,
    task_description: str,
    root: Path,
    *,
    model: str | None = None,
) -> tuple[Path, list[str]]:
    """LLM-assisted expertise creation: describe a task, get a skill bundle.

    Returns (index_path, selected_skill_names).
    """
    cfg_path = root / paths.ASM_TOML
    cfg = config.load(cfg_path)

    if not cfg.skills:
        raise ValueError("No skills installed. Add skills first with `asm add skill`.")

    selected = _llm_select_skills(task_description, cfg, model=model)
    if not selected:
        raise ValueError("LLM could not identify relevant skills for this task.")

    index_path = create_expertise(name, task_description, selected, root)
    return index_path, selected


def suggest(
    task_description: str,
    root: Path,
) -> list[tuple[str, float]]:
    """Match a task description against existing expertises using embeddings.

    Returns list of (expertise_name, similarity_score) sorted by relevance.
    """
    cfg_path = root / paths.ASM_TOML
    cfg = config.load(cfg_path)

    if not cfg.expertises:
        return []

    task_vec = embeddings.embed(task_description)

    results: list[tuple[str, float]] = []
    for name, ref in cfg.expertises.items():
        trigger_text = _build_trigger_text(name, ref)
        trigger_vec = embeddings.embed(trigger_text)
        sim = embeddings.cosine_similarity(task_vec, trigger_vec)
        results.append((name, sim))

    results.sort(key=lambda t: t[1], reverse=True)
    return results


def auto(
    task_description: str,
    root: Path,
    *,
    model: str | None = None,
) -> tuple[str, list[str]]:
    """Full autonomous flow: suggest or create expertise, install if needed, return best match.

    Returns (expertise_name, skill_names).
    """
    existing = suggest(task_description, root)
    if existing and existing[0][1] > 0.5:
        best_name = existing[0][0]
        cfg = config.load(root / paths.ASM_TOML)
        return best_name, _select_skills_for_execution(cfg.expertises[best_name])

    name = _slugify(task_description)
    _, selected = create_expertise_auto(name, task_description, root, model=model)
    return name, selected


def evaluate_routing_dataset(
    root: Path,
    dataset_path: Path,
    *,
    top_k: int = 3,
) -> RoutingEvaluationReport:
    """Evaluate routing quality against a deterministic benchmark dataset."""
    if top_k < 1:
        raise ValueError("top_k must be >= 1")

    cases = load_routing_dataset(dataset_path)
    if not cases:
        raise ValueError("Routing dataset is empty.")

    cfg = config.load(root / paths.ASM_TOML)
    if not cfg.expertises:
        raise ValueError("No expertises found. Create one with `asm create expertise`.")

    return _evaluate_cases(cases, cfg, top_k=top_k)


def load_routing_dataset(dataset_path: Path) -> list[RoutingBenchmarkCase]:
    """Load benchmark cases from .json or .jsonl."""
    if not dataset_path.exists():
        raise ValueError(f"Dataset not found: {dataset_path}")

    raw_text = dataset_path.read_text(encoding="utf-8").strip()
    if not raw_text:
        return []

    if dataset_path.suffix.lower() == ".jsonl":
        rows = [json.loads(line) for line in raw_text.splitlines() if line.strip()]
    else:
        parsed = json.loads(raw_text)
        if isinstance(parsed, dict):
            rows = parsed.get("cases", [])
        elif isinstance(parsed, list):
            rows = parsed
        else:
            raise ValueError("Dataset must be a JSON array or object with a `cases` field.")

    return [_parse_benchmark_row(row, idx) for idx, row in enumerate(rows, start=1)]


def enforce_routing_gates(
    report: RoutingEvaluationReport,
    *,
    min_top1: float | None = None,
    min_topk: float | None = None,
) -> None:
    """Raise ValueError when quality gates fail."""
    failures: list[str] = []
    if min_top1 is not None and report.top1_accuracy < min_top1:
        failures.append(
            f"top-1 accuracy gate failed: {report.top1_accuracy:.3f} < {min_top1:.3f}",
        )
    if min_topk is not None and report.topk_hit_rate < min_topk:
        failures.append(
            f"top-{report.top_k} hit-rate gate failed: {report.topk_hit_rate:.3f} < {min_topk:.3f}",
        )
    if failures:
        raise ValueError("; ".join(failures))


def _llm_select_skills(
    task_description: str,
    cfg: AsmConfig,
    *,
    model: str | None = None,
) -> list[str]:
    """Use LLM to pick the most relevant installed skills for a task."""
    from asm.services.llm import LLMClient, LLMError

    try:
        client = LLMClient(model=model)
    except LLMError:
        return _embedding_select_skills(task_description, cfg)

    skill_list = "\n".join(
        f"- {name}: {entry.source}" for name, entry in cfg.skills.items()
    )

    system = (
        "You select the most relevant skills for a given task. "
        "Reply with ONLY a comma-separated list of skill names. No explanation."
    )
    user = (
        f"Task: {task_description}\n\n"
        f"Available skills:\n{skill_list}\n\n"
        "Which skills are relevant for this task? List only their names, comma-separated."
    )

    try:
        raw = client.completion(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=256,
        )
        candidates = [s.strip().strip("`\"'") for s in raw.split(",")]
        installed = set(cfg.skills.keys())
        return [c for c in candidates if c in installed]
    except Exception:
        return _embedding_select_skills(task_description, cfg)


def _embedding_select_skills(
    task_description: str,
    cfg: AsmConfig,
    top_k: int = 5,
) -> list[str]:
    """Fallback: select skills using embedding similarity when LLM is unavailable."""
    task_vec = embeddings.embed(task_description)
    scored: list[tuple[str, float]] = []

    for name in cfg.skills:
        skill_vec = embeddings.embed(f"{name} {cfg.skills[name].source}")
        sim = embeddings.cosine_similarity(task_vec, skill_vec)
        scored.append((name, sim))

    scored.sort(key=lambda t: t[1], reverse=True)
    return [name for name, _ in scored[:top_k]]


def _slugify(text: str) -> str:
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower().strip())
    return slug.strip("-")[:50]


def _render_index(ref: ExpertiseRef, cfg: AsmConfig) -> str:
    title = ref.name.replace("-", " ").title()
    selected_skills = _select_skills_for_execution(ref)
    policies = ref.resolved_skill_policies()

    matrix_rows = []
    for policy in _sorted_policies(policies):
        deps = ", ".join(policy.depends_on) if policy.depends_on else "-"
        conflicts = ", ".join(policy.conflicts_with) if policy.conflicts_with else "-"
        advanced = "yes" if policy.is_advanced else "no"
        reason = policy.novelty_reason or "-"
        matrix_rows.append(
            f"| `{policy.name}` | {policy.role} | {advanced} | {deps} | {conflicts} | {reason} |"
        )

    lines = [
        f"# Expertise: {title}",
        "",
        ref.description,
        "",
        "## When to Choose This Group",
        "",
        "- Use this expertise when the task matches the domain signals below.",
        "- Prefer advanced skills first when they are available.",
        "- Resolve dependencies before invoking optional or fallback skills.",
        "",
        "## Task Signals",
        "",
    ]
    if ref.intent_tags:
        lines.append(f"- Intent tags: {', '.join(ref.intent_tags)}")
    if ref.task_signals:
        lines.append("- Task triggers:")
        for signal in ref.task_signals:
            lines.append(f"  - {signal}")
    if ref.confidence_hint:
        lines.append(f"- Confidence hint: {ref.confidence_hint}")
    lines.extend([
        "",
        "## Skill Selection Matrix",
        "",
        "| Skill | Role | Advanced | Depends on | Conflicts with | Novelty reason |",
        "| --- | --- | --- | --- | --- | --- |",
    ])
    lines.extend(matrix_rows)
    lines.extend([
        "",
        "## Routing Protocol",
        "",
    ])
    rubric = ref.selection_rubric or [
        "Pick this expertise only when at least one task signal matches.",
        "Load required skills, then advanced optional skills, then fallback if needed.",
        "Honor relationship constraints from relationships.md before execution.",
    ]
    for idx, step in enumerate(rubric, start=1):
        lines.append(f"{idx}. {step}")
    lines.extend([
        "",
        "## Selected Skills for Execution",
        "",
    ])
    for skill_name in selected_skills:
        entry = cfg.skills.get(skill_name)
        source = entry.source if entry else "unknown"
        lines.append(
            f"- **{skill_name}**: `.asm/skills/{skill_name}/SKILL.md` (source: `{source}`)"
        )
    lines.append("")
    return "\n".join(lines)


def _render_relationships(ref: ExpertiseRef) -> str:
    title = ref.name.replace("-", " ").title()
    policies = _sorted_policies(ref.resolved_skill_policies())
    selected = _select_skills_for_execution(ref)

    lines = [
        f"# Relationships: {title}",
        "",
        "## Skill Dependencies",
        "",
    ]
    for policy in policies:
        deps = ", ".join(policy.depends_on) if policy.depends_on else "none"
        lines.append(f"- `{policy.name}` depends on: {deps}")

    lines.extend([
        "",
        "## Valid Combinations",
        "",
    ])
    for policy in policies:
        if policy.role in {"required", "optional"}:
            lines.append(f"- `{policy.name}` is valid with required base skills.")

    lines.extend([
        "",
        "## Anti-Patterns",
        "",
    ])
    anti_patterns = 0
    for policy in policies:
        for conflict in policy.conflicts_with:
            anti_patterns += 1
            lines.append(f"- Do not combine `{policy.name}` with `{conflict}`.")
    if anti_patterns == 0:
        lines.append("- No explicit conflicts defined.")

    lines.extend([
        "",
        "## Execution Order",
        "",
    ])
    for idx, skill_name in enumerate(selected, start=1):
        lines.append(f"{idx}. `{skill_name}`")
    lines.append("")
    return "\n".join(lines)


def _default_skill_policies(skill_names: list[str]) -> list[SkillPolicy]:
    policies: list[SkillPolicy] = []
    for idx, skill_name in enumerate(skill_names):
        novelty_reason = _ADVANCED_SKILL_CLASSIFICATION.get(skill_name, "")
        policies.append(
            SkillPolicy(
                name=skill_name,
                role="required",
                execution_order=idx,
                is_advanced=bool(novelty_reason),
                novelty_reason=novelty_reason,
            )
        )
    return policies


def _sorted_policies(policies: list[SkillPolicy]) -> list[SkillPolicy]:
    return sorted(
        policies,
        key=lambda policy: (
            policy.execution_order if policy.execution_order is not None else 10_000,
            policy.name,
        ),
    )


def _select_skills_for_execution(ref: ExpertiseRef) -> list[str]:
    """Apply dependency/role logic and advanced preference for runtime selection."""
    policies = _sorted_policies(ref.resolved_skill_policies())
    if not policies:
        return []

    required = [p for p in policies if p.role == "required"]
    optional = [p for p in policies if p.role == "optional"]
    fallback = [p for p in policies if p.role == "fallback"]

    selected: list[str] = [policy.name for policy in required]

    if ref.prefer_advanced:
        advanced_optional = [policy for policy in optional if policy.is_advanced]
        selected.extend(policy.name for policy in advanced_optional)
        if not any(policy.is_advanced for policy in required + advanced_optional):
            advanced_fallback = [policy for policy in fallback if policy.is_advanced]
            if advanced_fallback:
                selected.append(advanced_fallback[0].name)
            elif fallback:
                selected.append(fallback[0].name)
    else:
        selected.extend(policy.name for policy in optional)
        if fallback:
            selected.append(fallback[0].name)

    expanded = _expand_dependencies(selected, policies)
    return _drop_conflicts(expanded, policies)


def _evaluate_cases(
    cases: list[RoutingBenchmarkCase],
    cfg: AsmConfig,
    *,
    top_k: int,
) -> RoutingEvaluationReport:
    trigger_vectors = _build_expertise_trigger_vectors(cfg)
    results: list[RoutingCaseResult] = []

    for case in cases:
        ranked = _rank_expertises(case.task, trigger_vectors)
        top_names = [name for name, _ in ranked]
        allowed = {case.expected_expertise, *case.allowed_alternatives}

        reciprocal_rank = 0.0
        for idx, name in enumerate(top_names, start=1):
            if name in allowed:
                reciprocal_rank = 1.0 / idx
                break

        top_slice = top_names[:top_k]
        top1_hit = bool(top_slice and top_slice[0] in allowed)
        topk_hit = any(name in allowed for name in top_slice)
        results.append(
            RoutingCaseResult(
                task=case.task,
                expected_expertise=case.expected_expertise,
                matched_expertise=top_names[0] if top_names else None,
                top_k_matches=top_slice,
                reciprocal_rank=reciprocal_rank,
                is_top1_hit=top1_hit,
                is_topk_hit=topk_hit,
            ),
        )

    total = len(results)
    top1 = sum(1 for r in results if r.is_top1_hit) / total
    topk = sum(1 for r in results if r.is_topk_hit) / total
    mrr = sum(r.reciprocal_rank for r in results) / total
    return RoutingEvaluationReport(
        total_cases=total,
        top_k=top_k,
        top1_accuracy=top1,
        topk_hit_rate=topk,
        mean_reciprocal_rank=mrr,
        case_results=results,
    )


def _build_expertise_trigger_vectors(cfg: AsmConfig) -> dict[str, list[float]]:
    vectors: dict[str, list[float]] = {}
    for name, ref in cfg.expertises.items():
        vectors[name] = embeddings.embed(_build_trigger_text(name, ref))
    return vectors


def _build_trigger_text(name: str, ref: ExpertiseRef) -> str:
    novelty = " ".join(
        policy.novelty_reason
        for policy in ref.resolved_skill_policies()
        if policy.novelty_reason
    )
    return " ".join(
        [
            name,
            ref.description,
            " ".join(ref.skills),
            " ".join(ref.intent_tags),
            " ".join(ref.task_signals),
            " ".join(ref.selection_rubric),
            novelty,
        ],
    )


def _rank_expertises(
    task_description: str,
    trigger_vectors: dict[str, list[float]],
) -> list[tuple[str, float]]:
    task_vec = embeddings.embed(task_description)
    scored = [
        (name, embeddings.cosine_similarity(task_vec, trigger_vec))
        for name, trigger_vec in trigger_vectors.items()
    ]
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored


def _parse_benchmark_row(raw: object, row_num: int) -> RoutingBenchmarkCase:
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid row {row_num}: expected JSON object.")

    task = str(raw.get("task", "")).strip()
    expected = str(raw.get("expected_expertise", "")).strip()
    allowed = raw.get("allowed_alternatives", [])
    notes = str(raw.get("notes", "")).strip()

    if not task:
        raise ValueError(f"Invalid row {row_num}: `task` is required.")
    if not expected:
        raise ValueError(f"Invalid row {row_num}: `expected_expertise` is required.")
    if not isinstance(allowed, list) or not all(isinstance(x, str) for x in allowed):
        raise ValueError(
            f"Invalid row {row_num}: `allowed_alternatives` must be a list of strings.",
        )

    return RoutingBenchmarkCase(
        task=task,
        expected_expertise=expected,
        allowed_alternatives=[x.strip() for x in allowed if x.strip()],
        notes=notes,
    )


def _expand_dependencies(selected: list[str], policies: list[SkillPolicy]) -> list[str]:
    policy_map = {policy.name: policy for policy in policies}
    resolved = list(selected)

    idx = 0
    while idx < len(resolved):
        current = resolved[idx]
        policy = policy_map.get(current)
        if policy:
            for dep in policy.depends_on:
                if dep in policy_map and dep not in resolved:
                    resolved.insert(idx, dep)
        idx += 1
    return resolved


def _drop_conflicts(selected: list[str], policies: list[SkillPolicy]) -> list[str]:
    policy_map = {policy.name: policy for policy in policies}
    role_map = {policy.name: policy.role for policy in policies}

    out: list[str] = []
    for skill_name in selected:
        policy = policy_map.get(skill_name)
        if not policy:
            out.append(skill_name)
            continue

        has_conflict = any(conflict in out for conflict in policy.conflicts_with)
        if not has_conflict:
            out.append(skill_name)
            continue

        if role_map.get(skill_name) == "required":
            out = [name for name in out if name not in policy.conflicts_with]
            out.append(skill_name)
    return out
