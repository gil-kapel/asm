---
title: Getting started
---

# Getting started

This page gives you the shortest path from zero to a working ASM workspace, then points to more detail where needed.

## 1. Install ASM

**Recommended:** use the install script (installs `uv` if needed, then ASM from the official wheel):

```bash
curl -LsSf https://raw.githubusercontent.com/gil-kapel/asm/main/install.sh | sh
```

**Manual install with uv:**

```bash
uv tool install --reinstall "https://github.com/gil-kapel/asm/releases/latest/download/asm-<version>-py3-none-any.whl"
```

Requirements: **Python 3.10+**.

## 2. Initialise a workspace

From your project root:

```bash
cd ~/my-project
asm init
```

You get:

```text
my-project/
├── asm.toml           # Project config & skill registry
└── .asm/
    ├── main_asm.md    # Root index — agents read this first
    ├── skills/        # Installed skill packages
    └── expertises/    # Task-oriented expertise bundles
```

## 3. Add skills

Install from GitHub, Smithery, Playbooks, or a local path:

```bash
asm add skill github/awesome-copilot/skills/refactor
asm add skill "https://smithery.ai/skill/mjunaidca/sqlmodel-database"
asm add skill ./path/to/local-skill
```

If skills are already listed in `asm.toml`, reconcile everything with:

```bash
asm sync
```

## 4. Match your task to an expertise

So agents know which skills to use for your task, match it to an expertise: run `asm expertise suggest "<task>"` to see matches, then `asm expertise auto "<task>"` to match or create an expertise, install any missing skills, and sync. This is how routing-by-expertise is configured.

## 5. Wire up agent integrations

After adding or changing skills or expertises, run `asm sync`. ASM regenerates `.asm/main_asm.md` from your **expertises** (and skills) and updates your IDE agent configs (Cursor / Claude / Codex / GitHub Copilot). See the [CLI reference](cli.md) and the README’s **Agent Integration** section for details.

## Next steps

- [Expertises](expertises.md) — why expertises and how routing works
- [CLI reference](cli.md) — full command list and options
- [Authoring skills](skills/authoring.md) — create and bundle skills
- [README on GitHub](https://github.com/gil-kapel/asm) — copy-paste prompt and full docs
