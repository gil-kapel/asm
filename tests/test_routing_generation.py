from pathlib import Path

import pytest

from asm.core.models import (
    AgentsConfig,
    AsmConfig,
    AsmMeta,
    ExpertiseRef,
    ProjectConfig,
    SkillEntry,
    SkillPolicy,
)
from asm.repo import config
from asm.services import integrations
from asm.services.expertise import (
    _select_skills_for_execution,
    enforce_routing_gates,
    evaluate_routing_dataset,
)
from asm.templates import render_main_asm


def _sample_config() -> AsmConfig:
    return AsmConfig(
        project=ProjectConfig(name="asm", version="0.1.0"),
        asm=AsmMeta(version="0.1.0"),
        skills={
            "sqlmodel-database": SkillEntry(
                name="sqlmodel-database",
                source="github:example/sqlmodel-database",
            ),
            "sql": SkillEntry(name="sql", source="playbooks:example/sql"),
            "documentation-standards": SkillEntry(
                name="documentation-standards",
                source="smithery:example/documentation-standards",
            ),
        },
        expertises={
            "db-layer": ExpertiseRef(
                name="db-layer",
                description="Database schema design and SQLModel operations.",
                skills=["sqlmodel-database", "sql", "documentation-standards"],
                intent_tags=["database", "schema"],
                task_signals=["migration", "query optimization"],
                confidence_hint="Prefer when schema and query words dominate the task.",
                selection_rubric=[
                    "Match DB task signals first.",
                    "Load required skills before optional skills.",
                ],
                prefer_advanced=True,
                skill_policies=[
                    SkillPolicy(
                        name="sqlmodel-database",
                        role="required",
                        is_advanced=True,
                        novelty_reason="Covers async session and MissingGreenlet patterns.",
                        execution_order=0,
                    ),
                    SkillPolicy(
                        name="sql",
                        role="optional",
                        is_advanced=True,
                        depends_on=["sqlmodel-database"],
                        execution_order=1,
                    ),
                    SkillPolicy(
                        name="documentation-standards",
                        role="fallback",
                        execution_order=2,
                    ),
                ],
            ),
        },
        agents=AgentsConfig(cursor=True, claude=False, codex=False),
    )


def test_config_roundtrip_with_skill_policies(tmp_path: Path) -> None:
    cfg = _sample_config()
    path = tmp_path / "asm.toml"
    config.save(cfg, path)

    loaded = config.load(path)
    ref = loaded.expertises["db-layer"]
    policy_map = {policy.name: policy for policy in ref.skill_policies}

    assert ref.prefer_advanced is True
    assert ref.intent_tags == ["database", "schema"]
    assert policy_map["sql"].role == "optional"
    assert policy_map["sql"].depends_on == ["sqlmodel-database"]
    assert policy_map["sqlmodel-database"].is_advanced is True


def test_main_router_and_cursor_entry_generation(tmp_path: Path) -> None:
    cfg = _sample_config()

    rendered = render_main_asm(cfg)
    assert "## Routing Protocol (Mandatory)" in rendered
    assert "## Expertise Group Router" in rendered
    assert "## Selection Rubric" in rendered
    assert "Advanced skills:" in rendered

    out = integrations.sync_cursor(tmp_path, cfg)
    cursor_md = out.read_text(encoding="utf-8")
    assert "## Mandatory Flow" in cursor_md
    assert "## Expertise Groups" in cursor_md
    assert "Do not pick directly from this list before expertise routing." in cursor_md


def test_advanced_skill_gate_prefers_advanced_optional() -> None:
    ref = ExpertiseRef(
        name="llm-integration",
        description="Structured output and browser automation.",
        skills=["llm-structured-output", "zendriver", "documentation-standards"],
        prefer_advanced=True,
        skill_policies=[
            SkillPolicy(name="llm-structured-output", role="required", execution_order=0),
            SkillPolicy(
                name="zendriver",
                role="optional",
                is_advanced=True,
                depends_on=["llm-structured-output"],
                execution_order=1,
            ),
            SkillPolicy(name="documentation-standards", role="fallback", execution_order=2),
        ],
    )

    selected = _select_skills_for_execution(ref)
    assert selected == ["llm-structured-output", "zendriver"]


def test_routing_eval_report_and_gate_enforcement(tmp_path: Path) -> None:
    cfg = AsmConfig(
        project=ProjectConfig(name="asm", version="0.1.0"),
        asm=AsmMeta(version="0.1.0"),
        skills={
            "sqlmodel-database": SkillEntry(
                name="sqlmodel-database",
                source="github:example/sqlmodel-database",
            ),
            "sql": SkillEntry(name="sql", source="playbooks:example/sql"),
            "cli-builder": SkillEntry(name="cli-builder", source="github:example/cli-builder"),
            "cli-ux": SkillEntry(name="cli-ux", source="local:example/cli-ux"),
        },
        expertises={
            "db-layer": ExpertiseRef(
                name="db-layer",
                description="Database schema design and SQLModel operations.",
                skills=["sqlmodel-database", "sql"],
                intent_tags=["database", "schema"],
                task_signals=["migration", "query optimization"],
            ),
            "cli-engineering": ExpertiseRef(
                name="cli-engineering",
                description="Command architecture and click UX.",
                skills=["cli-builder", "cli-ux"],
                intent_tags=["cli", "command"],
                task_signals=["click options", "subcommands", "help text"],
            ),
        },
        agents=AgentsConfig(cursor=True, claude=False, codex=False),
    )
    config.save(cfg, tmp_path / "asm.toml")

    dataset = tmp_path / "routing-benchmark.jsonl"
    dataset.write_text(
        "\n".join(
            [
                '{"task":"write sqlmodel migration for new user table","expected_expertise":"db-layer"}',
                '{"task":"design click subcommand with options and help","expected_expertise":"cli-engineering"}',
            ],
        ),
        encoding="utf-8",
    )

    report = evaluate_routing_dataset(tmp_path, dataset, top_k=2)
    assert report.total_cases == 2
    assert report.top_k == 2
    assert 0.0 <= report.top1_accuracy <= 1.0
    assert 0.0 <= report.topk_hit_rate <= 1.0
    assert 0.0 <= report.mean_reciprocal_rank <= 1.0
    assert len(report.case_results) == 2

    enforce_routing_gates(report, min_top1=0.0, min_topk=0.0)
    with pytest.raises(ValueError, match="top-1 accuracy gate failed"):
        enforce_routing_gates(report, min_top1=1.1)
