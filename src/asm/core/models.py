"""Data shapes for ASM configuration and skill metadata.

Skill structure follows the canonical SKILL.md format:
    skill-name/
    ├── SKILL.md          (required — YAML frontmatter + markdown body)
    ├── scripts/          (optional — executable code)
    ├── references/       (optional — docs loaded into context)
    └── assets/           (optional — files used in output)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


# ── Skill layer ─────────────────────────────────────────────────────


@dataclass
class SkillMeta:
    """Metadata extracted from SKILL.md YAML frontmatter."""
    name: str
    description: str
    trigger_phrases: list[str] = field(default_factory=list)
    version: str = "0.0.0"


@dataclass
class SkillResourceGroup:
    """Inventory for one resource directory inside a skill."""

    count: int = 0
    files: list[str] = field(default_factory=list)


@dataclass
class SkillResourceInventory:
    """Visible inventory for packaged skill resources."""

    references: SkillResourceGroup = field(default_factory=SkillResourceGroup)
    scripts: SkillResourceGroup = field(default_factory=SkillResourceGroup)
    examples: SkillResourceGroup = field(default_factory=SkillResourceGroup)
    assets: SkillResourceGroup = field(default_factory=SkillResourceGroup)


@dataclass
class EmbeddingProfile:
    """Versioned embedding metadata for trustable analysis/routing."""

    provider: str
    model: str
    dimension: int
    normalized: bool
    distance_metric: str
    embedding_version: str
    analysis_mode: str


@dataclass
class SkillManifest:
    """Structured manifest used by local/cloud skill analysis."""

    name: str
    description: str
    version: str = "0.0.0"
    trigger_phrases: list[str] = field(default_factory=list)
    resource_inventory: SkillResourceInventory = field(default_factory=SkillResourceInventory)
    source_ref: str = ""
    snapshot_id: str = ""
    integrity: str = ""


@dataclass
class SkillEvidence:
    """Evidence inventory attached to an analysis request."""

    source_urls: list[str] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)
    deepwiki_ref: str = ""
    evidence_digest: str = ""


@dataclass
class SkillFileRecord:
    """One transmitted file from a skill package."""

    path: str
    kind: Literal["skill_md", "reference", "script", "example", "asset", "other"]
    content: str


@dataclass
class SimilarSkillMatch:
    """Nearest-neighbor skill returned by the analyzer."""

    name: str
    similarity: float


AnalysisStatus = Literal["approved", "needs_work", "insufficient_evidence"]


@dataclass
class SkillScorecard:
    """Structured scorecard returned by local/cloud analysis."""

    skill_name: str
    analysis_id: str
    analysis_version: str
    trigger_specificity: float
    novelty: float
    evidence_grounding: float
    duplication_risk: float
    status: AnalysisStatus
    findings: list[str] = field(default_factory=list)
    recommended_actions: list[str] = field(default_factory=list)
    improvement_prompt: str = ""
    similar_skills: list[SimilarSkillMatch] = field(default_factory=list)
    created_at: str = ""


@dataclass
class SkillAnalysisArtifact:
    """Local persisted artifact for the latest analysis result."""

    manifest: SkillManifest
    evidence: SkillEvidence
    scorecard: SkillScorecard
    embedding_profile: EmbeddingProfile
    snapshot_id: str = ""
    integrity: str = ""


@dataclass
class SkillAnalysisRequest:
    """Payload sent from local ASM to the cloud analyzer."""

    manifest: SkillManifest
    evidence: SkillEvidence
    embedding_profile: EmbeddingProfile
    files: list[SkillFileRecord] = field(default_factory=list)


@dataclass
class SkillAnalysisResponse:
    """Cloud analyzer response returned to local ASM."""

    analysis_id: str
    analysis_version: str
    scorecard: SkillScorecard
    embedding_profile: EmbeddingProfile


@dataclass
class SkillEntry:
    """A skill registered in asm.toml [skills.<name>]."""
    name: str
    source: str  # "github:user/repo/path" | "local:./path" | "smithery:ns/skill"


@dataclass
class LockEntry:

    upstream_version: str = "0.0.0"
    local_revision: int = 0
    registry: str = ""
    integrity: str = ""
    resolved: str = ""
    snapshot_id: str = ""
    parent_snapshot_id: str = ""
    commit: str = ""


# ── Project layer ───────────────────────────────────────────────────


@dataclass
class ProjectConfig:
    """Mirrors the [project] table in asm.toml."""
    name: str
    version: str = "0.1.0"
    description: str = ""


@dataclass
class AsmMeta:
    """Mirrors the [asm] table — tool-level metadata."""
    version: str = "0.1.0"


@dataclass
class ExpertiseRef:
    """A reference to an active expertise namespace."""

    name: str
    description: str = ""
    skills: list[str] = field(default_factory=list)
    intent_tags: list[str] = field(default_factory=list)
    task_signals: list[str] = field(default_factory=list)
    confidence_hint: str = ""
    selection_rubric: list[str] = field(default_factory=list)
    prefer_advanced: bool = True
    skill_policies: list["SkillPolicy"] = field(default_factory=list)

    def resolved_skill_policies(self) -> list["SkillPolicy"]:
        """Return explicit policies, backfilling defaults for plain skill lists."""
        if not self.skill_policies:
            return [SkillPolicy(name=s) for s in self.skills]

        by_name = {policy.name: policy for policy in self.skill_policies}
        for skill_name in self.skills:
            if skill_name not in by_name:
                by_name[skill_name] = SkillPolicy(name=skill_name)

        ordered: list[SkillPolicy] = []
        for skill_name in self.skills:
            ordered.append(by_name.pop(skill_name))
        ordered.extend(by_name.values())
        return ordered


@dataclass
class SkillPolicy:
    """How a skill should be combined inside an expertise."""

    name: str
    role: Literal["required", "optional", "fallback"] = "required"
    depends_on: list[str] = field(default_factory=list)
    conflicts_with: list[str] = field(default_factory=list)
    execution_order: int | None = None
    is_advanced: bool = False
    novelty_reason: str = ""


@dataclass
class AgentsConfig:
    """Mirrors the [agents] table — which IDE integrations to sync."""

    cursor: bool = False
    claude: bool = False
    codex: bool = False
    copilot: bool = False


@dataclass
class AsmConfig:
    """Root configuration object for asm.toml."""

    project: ProjectConfig
    asm: AsmMeta = field(default_factory=AsmMeta)
    skills: dict[str, SkillEntry] = field(default_factory=dict)
    expertises: dict[str, ExpertiseRef] = field(default_factory=dict)
    agents: AgentsConfig = field(default_factory=AgentsConfig)


# ── Discovery layer ──────────────────────────────────────────────────


@dataclass
class DiscoveryItem:
    """Normalized search result across providers."""

    provider: str
    identifier: str
    name: str
    description: str
    url: str
    install_source: str
    stars: int | None = None
    tags: list[str] = field(default_factory=list)
    score: float = 0.0


# ── Routing evaluation layer ─────────────────────────────────────────


@dataclass
class RoutingBenchmarkCase:
    """One deterministic benchmark row for expertise routing."""

    task: str
    expected_expertise: str
    allowed_alternatives: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class RoutingCaseResult:
    """Evaluation result for a single benchmark case."""

    task: str
    expected_expertise: str
    matched_expertise: str | None
    top_k_matches: list[str] = field(default_factory=list)
    reciprocal_rank: float = 0.0
    is_top1_hit: bool = False
    is_topk_hit: bool = False


@dataclass
class RoutingEvaluationReport:
    """Aggregated routing quality metrics for a benchmark run."""

    total_cases: int
    top_k: int
    top1_accuracy: float
    topk_hit_rate: float
    mean_reciprocal_rank: float
    case_results: list[RoutingCaseResult] = field(default_factory=list)
