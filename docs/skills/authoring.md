---
title: Authoring skills
---

# Authoring skills

ASM treats each skill as a small, self‑contained package that captures non‑obvious patterns, workflows, or conventions for an agent. **Expertises** are the primary routing layer: agents choose one expertise for a task, then load only that group’s skills.

## Skill layout

Every skill lives under `.asm/skills/<name>/` and follows this structure:

```text
my-skill/
├── SKILL.md       # YAML frontmatter + instructions for the agent
├── scripts/       # Optional executable code (Python, shell, etc.)
└── references/    # Optional docs loaded into agent context
```

`SKILL.md` must contain at least:

```yaml
---
name: my-skill               # kebab‑case identifier
description: One‑line trigger description
---
```

## Creating skills

Use `asm create skill` to scaffold a new skill:

```bash
asm create skill cli-patterns "Reusable CLI command patterns"
```

You can also distill skills from existing code or repositories:

```bash
asm create skill discovery-notes "Discovery ranking guidance" --from ./src/asm/services/discovery.py
asm create skill sqlmodel-patterns "Async SQLModel usage" --from-repo tiangolo/sqlmodel
asm create skill pdf-helper "Extract text from PDFs" --ai
```

See `asm create skill --help` for the full set of flags (`--from`, `--from-url`, `--from-repo`, `--ai`, `--model`).

## Bundling expertises

Expertises group skills into task‑oriented bundles that agents can select autonomously:

```bash
asm create expertise routing-quality-engineering routing-evals embedding-ops python-testing \
  --desc "Deterministic expertise-routing quality with embedding diagnostics and regression gates"
```

Then match tasks to existing bundles:

```bash
asm expertise suggest "debug embedding similarity mismatches in expertise ranking"
asm expertise auto "improve expertise suggestion accuracy"
```

For the full picture (why expertises, how routing works), see [Expertises and routing](../expertises.md).

## Learn more

- For deeper authoring guidance and documentation standards, use the skills shipped with ASM (e.g. `documentation-standards`, `skill-development`) under `.asm/skills/`.
- [CLI reference](../cli.md) — full `asm create skill` and `asm expertise` options.

