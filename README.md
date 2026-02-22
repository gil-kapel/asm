# ASM — Agent Skill Manager


<p align="center">
  <img src="assets/asm-logo.svg" alt="ASM logo" width="250" />
</p>

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![CLI Click](https://img.shields.io/badge/cli-click-0ea5e9)](https://click.palletsprojects.com/)
[![Package Manager uv](https://img.shields.io/badge/package_manager-uv-7c3aed)](https://docs.astral.sh/uv/)

ASM manages a project-local `.asm/` skill graph and syncs it into Cursor / Claude / Codex.

- **Install curated skills** from GitHub, Smithery, and Playbooks
- **Lock reproducibility** with `asm.lock` integrity hashes
- **Sync context automatically** to active coding agent configs

[Quick Start](#quick-start) · [Usage](#usage) · [Agent Integration](#agent-integration) · [CLI Reference](#cli-reference)

## Copy Prompt For Your Agent

```text
Set up ASM in this project end-to-end.

ASM CLI (Agent Skill Manager) is a project-local skill orchestrator: it installs curated agent skills into `.asm/`, builds a root index (`.asm/main_asm.md`), and syncs those skills into the active agent config (Cursor/Claude/Codex).

1) Install ASM:
   curl -LsSf https://raw.githubusercontent.com/gil-kapel/asm/main/install.sh | sh

2) Initialize ASM in the current project root:
   asm init

3) Configure SkillsMP API access at user level:
   - create an API key at https://skillsmp.com
   - ensure `SKILLSMP_API_KEY` is set globally (not project-local), for example:
     mkdir -p ~/.asm-cli
     printf "SKILLSMP_API_KEY=sk_live_skillsmp_...\n" >> ~/.asm-cli/.env
   - verify search providers can use it

4) Discover the most relevant skills for this codebase:
   - infer stack/language/framework from the repo
   - run asm search with focused queries
   - pick top relevant skills only

5) Install the selected skills:
   - use the `source` field from asm search results
   - run asm add skill <source> for each selected skill

6) Sync integrations:
   asm sync

7) Output:
   - list installed skills
   - show which agent integration was synced (cursor/claude/codex)
   - report any provider/source failures and the fallback used
```

## Quick Start

```bash
# 1) Install ASM
curl -LsSf https://raw.githubusercontent.com/gil-kapel/asm/main/install.sh | sh

# 2) Initialize in your project
asm init

# 3) Find and add relevant skills
asm search "your stack or problem" --limit 5
asm add skill <source>

# 4) Sync into active agent context
asm sync
```

## Install

```bash
curl -LsSf https://raw.githubusercontent.com/gil-kapel/asm/main/install.sh | sh
```

Or with `wget`:

```bash
wget -qO- https://raw.githubusercontent.com/gil-kapel/asm/main/install.sh | sh
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

### Update ASM (no uninstall)

If a user is on an older ASM version, update in place:

```bash
asm update
```

`asm update` always updates from the official ASM repository and handles uninstall + reinstall automatically.

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

### Search federated skill registries

```bash
# Search across healthy providers only
asm search "sqlmodel"

# Limit result size
asm search "frontend design" --limit 5
```

ASM performs federated discovery across available providers (ASM index, Smithery, Playbooks, GitHub) and automatically skips providers that are unavailable at runtime.
Each result includes a `source` value you can copy directly into `asm add skill`.

### Add from Smithery / Playbooks links

```bash
# Direct provider URLs are supported
asm add skill "https://smithery.ai/skill/mjunaidca/sqlmodel-database"
asm add skill "https://playbooks.com/skills/openclaw/skills/sql"

# Provider refs are also supported
asm add skill "sm:mjunaidca/sqlmodel-database"
asm add skill "pb:openclaw/skills/sql"
```

### Configure SkillsMP API key

Some providers may require authentication (for higher rate limits or private access).  
Create a SkillsMP API key and expose it as an environment variable.

1. Log in to https://skillsmp.com
2. Open **Settings** (or **Developer / API Keys**)
3. Click **Create API Key**
4. Name the key (for example: `asm-local-dev`)
5. Copy the key and store it in a **user-level** env file (works across all projects)

```bash
mkdir -p ~/.asm-cli
cat >> ~/.asm-cli/.env <<'EOF'
SKILLSMP_API_KEY=sk_live_skillsmp_...
EOF
```

ASM automatically reads user-level env files on startup (without overriding already-exported shell variables):

- `~/.asm-cli/.env`
- `~/.config/asm/env`
- `~/.config/asm/.env`

If you prefer shell profile exports, this also works:

```bash
echo 'export SKILLSMP_API_KEY=sk_live_skillsmp_...' >> ~/.zshrc
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

### Team registry versioning flow

Use this flow when your team imports a base skill, customizes it locally, and manages versions in your own registry.

```bash
# 1) Import from upstream registry/source
asm add skill https://github.com/github/awesome-copilot/tree/main/skills/refactor

# 2) Edit the local working tree
$EDITOR .asm/skills/refactor/SKILL.md

# 3) Save WIP without creating a new local revision
asm skill stash push refactor -m "wip: adjust prompts for team style"

# 4) Restore WIP later
asm skill stash apply refactor

# 5) Create a local version revision
asm skill commit refactor -m "team: add stricter refactor checklist"

# 6) Add a human tag for release workflows
asm skill tag refactor team-v1

# 7) Roll backward/forward by tag or snapshot id
asm skill checkout refactor team-v1
asm skill checkout refactor <snapshot_id>

# 8) Inspect version timeline
asm skill history refactor
```

### Single-user local registry flow

Use this when one developer manages personal variants in a local filesystem registry/workspace.

```bash
# 1) Create/import your base skill
asm create skill prompt-tuning "Personal prompt refinement patterns"
# or: asm add skill ./my-local-skill

# 2) Iterate locally
$EDITOR .asm/skills/prompt-tuning/SKILL.md

# 3) Save temporary experiments
asm skill stash push prompt-tuning -m "wip: experiment with shorter instructions"

# 4) Commit a personal version
asm skill commit prompt-tuning -m "me: stable concise prompt style"

# 5) Tag your own milestones
asm skill tag prompt-tuning me-v1

# 6) Jump between known-good versions
asm skill checkout prompt-tuning me-v1
asm skill history prompt-tuning
```

Version model used by ASM lock entries:
- `upstream_version`: version coming from the imported/origin skill.
- `local_revision`: monotonic team/user revision in your registry.
- `registry`/`registry_id`: where ownership of the local evolution lives.
- `origin_registry`/`origin_ref`: immutable provenance of the first import.

If your repo has older lockfiles, run migration once:

```bash
asm lock migrate
```

## Agent Integration

ASM skills live in `.asm/`, but each IDE agent reads its own config location. Agent configs are synced automatically after every `asm add skill`, `asm create skill`, and `asm sync`.

### What gets generated

| Agent | File | Behaviour |
|---|---|---|
| Cursor | `.cursor/skills/asm/SKILL.md` | Cursor skill pointing to `.asm/main_asm.md` |
| Claude Code | `CLAUDE.md` | Sentinel-guarded section (preserves your content) |
| Codex | `AGENTS.md` | Sentinel-guarded section (preserves your content) |

### Context-aware sync vs explicit config

ASM chooses sync targets in this priority:

1. Explicit `[agents]` config in `asm.toml`
2. Runtime context inference (Cursor/Claude/Codex session signals)
3. Project marker detection (`.cursor/`, `CLAUDE.md`, `AGENTS.md`)
4. Fallback to Cursor (creates `.cursor/skills/asm/SKILL.md` if needed)

You can force a one-off runtime context with:

```bash
ASM_AGENT=cursor asm sync
ASM_AGENT=claude asm sync
ASM_AGENT=codex asm sync
```

To lock it down, add an `[agents]` table to `asm.toml`:

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
| `asm search <query>` | Federated discovery across healthy registries/providers |
| `asm add skill <source>` | Install a skill from GitHub or local path |
| `asm create skill <name> <desc>` | Scaffold a new skill package |
| `asm create skill <name> <desc> --from <path>` | Create a skill from existing code |
| `asm sync` | Install missing skills, verify integrity, sync agent configs |
| `asm update` | Update ASM CLI in place (no manual uninstall required) |
| `asm skill commit <name> -m <msg>` | Create a new local skill revision |
| `asm skill stash push <name> [-m <msg>]` | Save WIP snapshot without version bump |
| `asm skill stash apply <name> [stash_id]` | Restore a stashed snapshot |
| `asm skill tag <name> <tag> [ref]` | Assign a tag to HEAD or a snapshot ref |
| `asm skill checkout <name> <ref>` | Materialize a tagged/snapshotted version |
| `asm skill history <name>` | Show recent version history for a skill |
| `asm skill status <name>` | Show unstaged file status vs locked snapshot |
| `asm skill diff <name> [rel_path]` | Show unified diff vs locked snapshot |
| `asm lock migrate` | Upgrade `asm.lock` schema in place |
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
