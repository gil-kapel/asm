# ASM — Agent Skill Manager

A CLI that gives your IDE agent (Cursor, Claude Code, Aider) **SOTA expertise** instead of average training data.

ASM manages a `.asm/` directory in your project — a structured skill library that agents read before every task. Think `npm` for agent knowledge: install curated skills from GitHub, scaffold your own, and bundle them into domain expertises.

## Install

```bash
curl -LsSf https://raw.githubusercontent.com/gil-kapel/asm/install.sh | sh
```

Or with `wget`:

```bash
wget -qO- https://raw.githubusercontent.com/gil-kapel/asm/install.sh | sh
```

The script detects your system, installs [uv](https://docs.astral.sh/uv/) if needed, clones the repo, and makes the `asm` command available globally. No sudo required.

**Requirements:** Python 3.10+, git

### Manual install

If you prefer doing it yourself:

```bash
git clone https://github.com/gil-kapel/asm.git ~/.asm-cli
uv tool install -e ~/.asm-cli
```

Verify:

```bash
asm --version
```

### Uninstall

```bash
uv tool uninstall asm && rm -rf ~/.asm-cli
```

## Usage

### Initialise a workspace

```bash
cd ~/my-project
asm init
```

This creates:

```
my-project/
├── asm.toml           # Project config & skill registry
└── .asm/
    ├── main_asm.md    # Root index — agents read this first
    └── skills/        # Installed skill packages
```

### Add a skill from GitHub

```bash
# Full URL
asm add skill https://github.com/github/awesome-copilot/tree/main/skills/refactor

# Shorthand
asm add skill github/awesome-copilot/skills/refactor

# Override the name
asm add skill user/repo/path --name my-refactor
```

ASM clones the skill, validates its `SKILL.md`, installs it under `.asm/skills/`, and updates `asm.toml` + `asm.lock`.

### Add a local skill

```bash
asm add skill ./path/to/my-skill
asm add skill local:../shared-skills/testing
```

### Create a skill from scratch

```bash
asm create skill api-patterns "REST API design patterns for FastAPI services"
```

Scaffolds a new skill package:

```
.asm/skills/api-patterns/
├── SKILL.md       # Frontmatter + instructions for the agent
├── scripts/       # Executable code for deterministic tasks
└── references/    # Docs loaded into agent context as needed
```

### Create a skill from existing code

```bash
asm create skill db-layer "Async SQLAlchemy repository pattern" --from ./src/database.py
```

Source files are analysed and placed into `scripts/` (`.py`, `.sh`) or `references/` (everything else).

### Sync workspace

```bash
asm sync
```

Like `uv sync` — reads `asm.toml` and reconciles your `.asm/skills/` directory:

- **Missing skills** are fetched from their declared source (GitHub / local)
- **Existing skills** are verified against their `asm.lock` integrity hash
- **Stale lockfile entries** (removed from `asm.toml`) are pruned
- After installing, `main_asm.md` is regenerated and agent configs are synced

This is the team onboarding command:

```bash
git clone <repo> && cd <repo> && asm sync
```

## Agent Integration

ASM skills live in `.asm/`, but each IDE agent reads its own config location. Agent configs are synced automatically after every `asm add skill`, `asm create skill`, and `asm sync`.

### What gets generated

| Agent | File | Behaviour |
|---|---|---|
| Cursor | `.cursor/skills/asm/SKILL.md` | Cursor skill pointing to `.asm/main_asm.md` |
| Claude Code | `CLAUDE.md` | Sentinel-guarded section (preserves your content) |
| Codex | `AGENTS.md` | Sentinel-guarded section (preserves your content) |

### Auto-detection vs explicit config

By default, ASM auto-detects agents (`.cursor/` exists? sync Cursor). To lock it down, add an `[agents]` table to `asm.toml`:

```toml
[agents]
cursor = true
claude = true
codex = false
```

When `[agents]` is configured, only those set to `true` are synced.

## How it works

```
asm.toml          Declares which skills are active + their sources
asm.lock          Pins SHA-256 integrity hashes for reproducibility
.asm/main_asm.md  Root document — agents read this first
.asm/skills/      Each skill is a self-contained SKILL.md package
```

When an agent starts a task, it reads `.asm/main_asm.md`, which lists every installed skill and points to its `SKILL.md`. The agent follows the blueprints, templates, and pitfall warnings defined in each skill — producing code that matches curated expertise instead of generic completions.

### Skill anatomy

Every skill follows the canonical `SKILL.md` format:

```
my-skill/
├── SKILL.md          # Required — YAML frontmatter (name, description) + body
├── scripts/          # Optional — runnable code
├── references/       # Optional — context docs
└── assets/           # Optional — output files
```

The `SKILL.md` frontmatter is validated on install:

```yaml
---
name: my-skill
description: One-line explanation used for agent triggering
---
```

`name` must be kebab-case. Both `name` and `description` are required.

### The sync lifecycle

```
asm.toml ──► asm sync ──► .asm/skills/       (fetch missing)
                      ──► asm.lock           (verify / update hashes)
                      ──► main_asm.md        (regenerate index)
                      ──► agent configs      (Cursor / Claude / Codex)
```

## CLI Reference

| Command | Description |
|---|---|
| `asm init` | Initialise workspace (`asm.toml` + `.asm/`) |
| `asm add skill <source>` | Install a skill from GitHub or local path |
| `asm create skill <name> <desc>` | Scaffold a new skill package |
| `asm create skill <name> <desc> --from <path>` | Create a skill from existing code |
| `asm sync` | Install missing skills, verify integrity, sync agent configs |
| `asm create expertise <skills...> --desc <desc>` | Bundle skills into a domain *(coming soon)* |
| `asm --version` | Print version |

## Development

```bash
git clone https://github.com/gil-kapel/asm.git
cd asm
uv sync
uv run asm --version
```

The CLI entry point is `src/asm/cli/__init__.py`, registered as `asm` via `pyproject.toml`:

```toml
[project.scripts]
asm = "asm.cli:cli"
```

## License

MIT
