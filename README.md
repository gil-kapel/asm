# ASM — Agent Skill Manager


<p align="center">
  <img src="assets/asm-logo.svg" alt="ASM logo" width="250" />
</p>

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![CLI Click](https://img.shields.io/badge/cli-click-0ea5e9)](https://click.palletsprojects.com/)
[![Package Manager uv](https://img.shields.io/badge/package_manager-uv-7c3aed)](https://docs.astral.sh/uv/)

ASM manages a project-local `.asm/` skill graph and syncs it into Cursor / Claude / Codex.

- **Curated Index**: Verified, high-quality skills with non-obvious knowledge and actionable patterns.
- **Expertise Layer**: Bundle skills into task-oriented domains for autonomous agent selection and auto-configuration.
- **Semantic Search**: Embedding-based lookup (via OpenAI embeddings) with local caching for sub-second relevance.
- **Reproducible Graphs**: `asm.toml` + `asm.lock` pin exact skill sources and hashes.
- **Zero-Touch Sync**: Keeps Cursor / Claude / Codex configs in sync with your `.asm/` graph.

[Quick Start](#quick-start) · [Example workflows](#example-workflows) · [Usage](#usage) · [How skill graphs work](#how-skill-graphs-work) · [CLI map](#cli-map) · [Agent Integration](#agent-integration)

## TL;DR

- **What ASM is**: A project-local skill manager for agents that installs skills into `.asm/`, bundles them into *expertises*, and syncs a single `main_asm.md` index that your IDE agents read first.
- **Why you care**: New projects (or new machines) can get the exact same "brain" in one command (`asm sync`), instead of copy-pasting prompts and skills by hand.
- **Fast path**:
  1. `curl -LsSf https://raw.githubusercontent.com/gil-kapel/asm/main/install.sh | sh`
  2. `asm init` in your repo
  3. `asm search "<your stack or problem>"` → `asm add skill <source>`
  4. `asm expertise auto "<task description>"` → `asm sync`

## Copy Prompt For Your Agent

Use this prompt in **any** agent (Cursor, Claude Code, Codex, GitHub Copilot, or other) to set up ASM in the project.

```text
Set up ASM in this project and leave it in a working state.

ASM (Agent Skill Manager) is a project-local skill system. It installs skills into `.asm/`, builds `.asm/main_asm.md`, groups skills into expertises, and syncs the router into the active agent config.

Do this in order:

1. Check whether `asm` is already installed. If not, install it with:
   `curl -LsSf https://raw.githubusercontent.com/gil-kapel/asm/main/install.sh | sh`

2. Check whether this repo already has ASM initialized by looking for `asm.toml`.
   - If ASM is not initialized, run `asm init`.
   - If ASM is already initialized, do not recreate it.

3. Inspect the current project briefly and choose the most relevant skill search queries for this repo.
   - Prefer curated, high-signal skills.
   - Do not install a large pile of generic skills.

4. Search and install only the most relevant skills.
   - Use `asm search "<query>"`.
   - Use `asm add skill <source>` for the best matches.

5. Configure expertise routing for the current project task or stack.
   - Run `asm expertise auto "<task description>"` with a concrete description of what this project needs.

6. Sync ASM into the active agent config.
   - Run `asm sync`.

7. If `ASM_CLOUD_API_URL` is configured and there is at least one local skill worth checking, run one cloud analysis:
   - `asm skill analyze <skill-name> --cloud`

8. At the end, report:
   - whether ASM was installed or already present
   - whether the workspace was initialized or already initialized
   - which skills were installed
   - which expertise was selected or created
   - which agent config(s) were synced
   - whether cloud analysis was run, and where the scorecard was saved

Success criteria:
- `asm.toml` exists
- `.asm/main_asm.md` exists
- at least one relevant skill is installed
- at least one expertise is active or created
- agent sync completed successfully
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

# 4) Route task to expertises and validate routing quality
asm expertise auto "improve expertise suggestion accuracy"
asm expertise eval --dataset ./tests/routing_benchmark.jsonl --min-top1 0.80 --min-topk 0.95

# 5) Sync into active agent context
asm sync
```

## Example workflows

### 1. Onboard into an existing repo

```bash
git clone https://github.com/your-org/your-repo.git
cd your-repo
asm sync
```

Example output:

```text
↓ sqlmodel-database (github:tiangolo/sqlmodel)… 
✔ sqlmodel-database installed (320ms)
✔ sql (no lock entry)
  ↻ synced cursor → .cursor/skills/asm/SKILL.md
✔ Synced 2 skill(s) in 0.6s
```

Now your agent sees the same skills and expertises as the rest of the team.

### 2. Discover and install a curated skill

```bash
cd ~/my-project
asm init
asm search "sqlmodel repository" --limit 3
asm add skill pb:openclaw/skills/sql
```

Example output:

```text
Found 1 result(s):
1. [playbooks] sql
   id: openclaw/skills/sql
   url: https://playbooks.com/skills/openclaw/skills/sql
   source: pb:openclaw/skills/sql
   SQL utility patterns for agents

↓ sql (pb:openclaw/skills/sql)…
✔ sql installed (410ms)
  ↻ synced cursor → .cursor/skills/asm/SKILL.md
✔ Installed skill: sql
  SQL utility patterns for agents
  → .asm/skills/sql/SKILL.md
```

### 3. Let ASM build an expertise bundle for a task

```bash
asm expertise auto "build a REST API with database migrations"
```

Example output:

```text
Matching task to expertises…
✔ Expertise: db-layer-plus
  Skills: sqlmodel-database, sql, python-testing
  → .asm/expertises/db-layer-plus/index.md
  ↻ synced cursor → .cursor/skills/asm/SKILL.md
```

Your agent now has a guided path (via the expertise docs) instead of a flat pile of skills.

## Install

```bash
curl -LsSf https://raw.githubusercontent.com/gil-kapel/asm/main/install.sh | sh
```

Or with `wget`:

```bash
wget -qO- https://raw.githubusercontent.com/gil-kapel/asm/main/install.sh | sh
```

The script detects your system, installs [uv](https://docs.astral.sh/uv/) if needed, and installs ASM from the official release wheel. No sudo required.

**Requirements:** Python 3.10+

### Manual install

If you prefer doing it yourself (same release wheel used by `install.sh`):

```bash
uv tool install --reinstall "https://github.com/gil-kapel/asm/releases/latest/download/asm-<version>-py3-none-any.whl"
```

**Note:** If the project has no releases yet, or to get the latest development version, install from source:

```bash
uv tool install git+https://github.com/gil-kapel/asm
```

### Local Development

If you are developing ASM locally:

```bash
uv tool install --editable .
```

Verify:

```bash
asm --version
```

### Update ASM

To update to the latest version from source:

```bash
uv tool upgrade asm --from git+https://github.com/gil-kapel/asm
```

Or just use the built-in update:

```bash
asm update
```

`asm update` is resilient: it tries to update from the official release wheel first, and falls back to the source (git) if no valid release is found.

### Uninstall

```bash
uv tool uninstall asm && rm -rf ~/.asm-cli
```

## Releases & Changelog

- **Versioning**: ASM follows semantic versioning (`MAJOR.MINOR.PATCH`), with the canonical version defined in `pyproject.toml`.
- **Changelog**: All notable changes are recorded in `CHANGELOG.md` (Keep a Changelog format).
- **Release flow** (manual, via Git tags and GitHub releases):
  1. Update the version in `pyproject.toml`.
  2. Update `CHANGELOG.md`, moving entries from **Unreleased** into a new version section.
  3. Commit changes and create a tag, e.g. `git tag v0.1.0`.
  4. Build wheels with `uv build` and attach them to a GitHub release for that tag.

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

Important: `asm add skill` requires a source reference, not a skill name.

```bash
# Invalid (skill name only)
asm add skill sql

# Valid (provider ref or URL)
asm add skill pb:openclaw/skills/sql
asm add skill https://playbooks.com/skills/openclaw/skills/sql

# If already declared in asm.toml, install all missing declared skills
asm sync
```

### Add a local skill

```bash
asm add skill ./path/to/my-skill
asm add skill local:../shared-skills/testing
```

### Search curated and federated registries

```bash
# Search across curated index and healthy providers
asm search "database patterns"

# Limit result size
asm search "frontend design" --limit 5
```

ASM performs federated discovery across available providers (ASM index, Smithery, Playbooks, GitHub, SkillsMP).
- **[curated]**: Verified skills with quality scoring rank first.
- **Semantic Ranking**: Query embeddings (via OpenAI embeddings) are matched against skill triggers for high relevance.
- **Local Cache**: Embeddings are cached in `~/.asm-cli/embeddings.msgpack` for instant search.

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

SkillsMP access is optional. If you want SkillsMP-backed discovery, create your own API key and expose it as an environment variable.

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

Recommended placement: `~/.asm-cli/.env` (avoid project `.env` files so keys are not committed by mistake).

If you prefer shell profile exports, this also works:

```bash
echo 'export SKILLSMP_API_KEY=sk_live_skillsmp_...' >> ~/.zshrc
```

### Configure ASM cloud analyzer

Skill analysis can run locally with OpenAI or in the managed cloud.

For local analysis, configure an OpenAI model and key:

```bash
mkdir -p ~/.asm-cli
cat >> ~/.asm-cli/.env <<'EOF'
ASM_LLM_MODEL=openai/gpt-5-mini
OPENAI_API_KEY=sk-...
EOF
```

Run:

```bash
asm skill analyze my-skill --local
asm skill analyze my-skill --local --model openai/gpt-5-mini
```

For cloud analysis, set the analyzer URL in a user-level env file:

```bash
mkdir -p ~/.asm-cli
cat >> ~/.asm-cli/.env <<'EOF'
ASM_CLOUD_API_URL=http://127.0.0.1:8000
ASM_CLOUD_API_KEY=dev-token
EOF
```

Recognized user-level env locations:

- `~/.asm-cli/.env`
- `~/.config/asm/env`
- `~/.config/asm/.env`

Analyze one local skill:

```bash
asm skill analyze my-skill --local
asm skill analyze my-skill --cloud
asm skill analyze my-skill --cloud --api-url http://127.0.0.1:8000
```

ASM stores the latest scorecard under `.asm/analysis/<skill>/latest.json`.

### Run the cloud MVP backend locally

Install the optional cloud dependencies and run the FastAPI app:

```bash
uv sync --extra cloud
uv run uvicorn backend.api:app --reload
```

Optional backend env vars:

- `ASM_CLOUD_STORE`: directory used by the backend to persist analyses and manifest corpus
- `ASM_CLOUD_ANALYZER_VERSION`: version string returned in scorecards


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

### Expertise: Autonomous Skill Bundling

Expertises group multiple skills into task-oriented domains. Agents can autonomously match your natural language task to the right expertise.

```bash
# 1) Create a bundle of installed skills
asm create expertise routing-quality-engineering routing-evals embedding-ops python-testing \
  --desc "Deterministic expertise-routing quality with embedding diagnostics and regression gates"

# 2) Match a task to existing expertises (sub-second similarity check)
asm expertise suggest "debug embedding similarity mismatches in expertise ranking"

# 3) Full autonomous flow: match or create, install missing, and sync
asm expertise auto "improve expertise suggestion accuracy"

# 4) Evaluate routing quality against a benchmark dataset
asm expertise eval --dataset ./tests/routing_benchmark.jsonl --top-k 3 --min-top1 0.80 --min-topk 0.95
```

### Advanced Skill Creation (Deep Repo Analysis)

Instead of manual writing, ASM can distill complex patterns from entire GitHub repositories or local directories using AI.

```bash
# Create a skill from a GitHub repo (README, source files, and structure)
asm create skill sqlmodel-patterns "Async SQLModel usage" --from-repo tiangolo/sqlmodel

# Search GitHub for top repos, then enrich generation from those matches
asm create skill sqlmodel-patterns "Async SQLModel usage" --github-search "sqlmodel fastapi async"

# Create from a local module
asm create skill auth-utils "Project auth conventions" --from ./src/auth/ --ai
```

- **`--from-repo OWNER/REPO`**: Fetches the README, directory structure, and key source files via GitHub API as context for the LLM.
- **`--github-search QUERY`**: Searches GitHub repositories, picks the top matches, and enriches the skill with DeepWiki-style repo context from those results.
- **`--github-search-limit`**: Caps how many search-result repos are used for enrichment.
- **`--ai`**: Use OpenAI to generate sophisticated instructions, usage guidelines, and examples.
- **`--from ./path`**: Analyzes local code to extract internal patterns and conventions.

### AI-assisted skill creation (OpenAI)

ASM can generate SKILL.md content (Instructions, Usage, Examples) using the OpenAI API. Install ASM and set `OPENAI_API_KEY`:

```bash
uv tool install asm   # or: pip install asm
export OPENAI_API_KEY=sk-...
```

Create a skill with generated content:

```bash
asm create skill pdf-helper "Extract text and tables from PDFs" --ai
asm create skill cli-ux "CLI UX patterns for Click" --ai --model openai/gpt-5-mini
asm create skill sqlmodel-database "Async SQLModel patterns" --loop --target-score 0.9 --max-tries 5
asm create skill sqlmodel-database "Async SQLModel patterns" --github-search "sqlmodel alembic async"
```

- **`--ai`**: Use OpenAI to generate the skill description and body.
- **`--loop`**: Turn on a build -> analyze -> rewrite loop. ASM uses the local scorecard's `improvement_prompt`, and when `evidence_grounding` or `trigger_specificity` is low it automatically fetches DeepWiki/GitHub evidence and materializes it into `references/research-iteration-<n>.md` before rewriting.
- **`--model`**: OpenAI model string (default: `gpt-4o-mini`). Can be set with `ASM_LLM_MODEL`.
- **`--target-score`**: Loop stop threshold from `0.0` to `1.0` for the aggregate local analysis score.
- **`--max-tries`**: Maximum number of build/analyze/rewrite passes when `--loop` is enabled.
- **`--from ./path`**: Local file or directory; the LLM receives its content as context.
- **`--from-url URL`**: Fetch content from a URL and use it as context for the LLM. Supports GitHub API contents (e.g. `https://api.github.com/repos/owner/repo/contents/README.md?ref=main`) and raw URLs; directories are expanded by fetching each file.
- **`--github-search QUERY`**: Search GitHub repos, fetch the top repo docs and key files, and use that bundle as extra LLM context.

ASM now uses the native OpenAI client. `--model` accepts either raw OpenAI model names like `gpt-5-mini` or `openai/gpt-5-mini`.

### Share your skill

ASM treats custom skill creation as a core workflow: build locally, analyze it, improve it, then package it for sharing.

```bash
asm skill analyze langgraph-skill-builder --local
asm skill share langgraph-skill-builder
```

`asm skill share` creates:

- `dist/skills/<name>/` with the full skill package
- `dist/skills/<name>.zip` for easy publishing
- `share.json` with integrity and snapshot metadata
- publish the folder or zip to GitHub, a registry, or any public repo

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

| Agent | File(s) | Behaviour |
|---|---|---|
| Cursor | `.cursor/skills/asm/SKILL.md` | Router skill pointing to `.asm/main_asm.md` |
| Claude Code | `CLAUDE.md` + `.claude/skills/asm/SKILL.md` | Sentinel in CLAUDE.md; router skill in `.claude/skills/` for Claude Code discovery |
| Codex | `AGENTS.md` | Sentinel-guarded section (preserves your content) |
| GitHub Copilot | `.github/skills/asm/SKILL.md` | Router skill for Copilot coding agent / VS Code (same format as Cursor/Claude) |

### Context-aware sync vs explicit config

ASM chooses sync targets in this priority:

1. Explicit `[agents]` config in `asm.toml`
2. Runtime context inference (Cursor/Claude/Codex session signals)
3. Project marker detection (`.cursor/`, `CLAUDE.md`, `AGENTS.md`, `.github/skills/`)
4. Fallback to Cursor (creates `.cursor/skills/asm/SKILL.md` if needed)

You can force a one-off runtime context with:

```bash
ASM_AGENT=cursor asm sync
ASM_AGENT=claude asm sync
ASM_AGENT=codex asm sync
ASM_AGENT=copilot asm sync
```

To lock it down, add an `[agents]` table to `asm.toml`:

```toml
[agents]
cursor = true
claude = true
codex = false
copilot = true   # GitHub Copilot coding agent / VS Code → .github/skills/asm/SKILL.md
```

When `[agents]` is configured, only those set to `true` are synced.

## How skill graphs work

```
asm.toml          Declares which skills are active + their sources
asm.lock          Pins SHA-256 integrity hashes for reproducibility
.asm/main_asm.md  Root document — agents read this first
.asm/skills/      Each skill is a self-contained SKILL.md package
```

When an agent starts a task, it reads `.asm/main_asm.md`, which lists every installed skill and points to its `SKILL.md`. The agent follows the blueprints, templates, and pitfall warnings defined in each skill — producing code that matches curated expertise instead of generic completions.

High-level flow:

```mermaid
graph TD
  A[asm.toml] --> B[.asm/skills/*]
  A --> C[.asm/expertises/*]
  B --> D[.asm/main_asm.md]
  C --> D
  D --> E[Cursor/Claude/Codex configs]
  E --> F[Your agent runtime]
```

- **Skills** live under `.asm/skills/*/SKILL.md` and hold reusable blueprints.
- **Expertises** (`.asm/expertises/*`) wire multiple skills together for a domain.
- **`main_asm.md`** is the single entrypoint agents read to discover what they can do.

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

## CLI map

- **Workspace bootstrap**: `asm init`, `asm sync`, `asm lock migrate`
- **Skill lifecycle**: `asm search`, `asm add skill`, `asm skill list`, `asm create skill`, `asm skill …`
- **Expertise & routing**: `asm create expertise`, `asm expertise list`, `asm expertise skills`, `asm expertise suggest`, `asm expertise auto`, `asm expertise eval`
- **ASM itself**: `asm update`, `asm --version`

### Full CLI reference

| Command | Description |
|---|---|
| `asm init` | Initialise workspace (`asm.toml` + `.asm/`) |
| `asm search <query>` | Federated discovery across healthy registries/providers |
| `asm add skill <source>` | Install a skill from GitHub or local path |
| `asm skill list` | List skills registered in the workspace |
| `asm skill analyze <name> --local` | Analyze one local skill with OpenAI using `ASM_LLM_MODEL` and `OPENAI_API_KEY` |
| `asm skill analyze <name> --cloud` | Submit one local skill to the optional ASM cloud analyzer |
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
| `asm create expertise <name> <skills...>` | Bundle skills into a task-oriented domain |
| `asm expertise list` | List expertises defined in the workspace |
| `asm expertise skills <name>` | List skills in an expertise |
| `asm expertise suggest <task>` | Match a task to existing expertises (semantic) |
| `asm expertise auto <task>` | Autonomous match/create and configuration |
| `asm expertise eval --dataset <file>` | Evaluate routing quality (top-1/top-k/MRR) and enforce gates |
| `asm --version` | Print version |

### Shell autocomplete

ASM uses Click shell completion, including dynamic workspace values like installed skills, expertise names, snapshot refs, and stash ids.

Enable it in zsh:

```bash
echo 'eval "$(_ASM_COMPLETE=zsh_source asm)"' >> ~/.zshrc
source ~/.zshrc
```

Enable it in bash:

```bash
echo 'eval "$(_ASM_COMPLETE=bash_source asm)"' >> ~/.bashrc
source ~/.bashrc
```

Enable it in fish:

```bash
mkdir -p ~/.config/fish/completions
_ASM_COMPLETE=fish_source asm > ~/.config/fish/completions/asm.fish
```

## CLI Reference

| Command | Description |
|---|---|
| `asm init` | Initialise workspace (`asm.toml` + `.asm/`) |
| `asm search <query>` | Federated discovery across healthy registries/providers |
| `asm add skill <source>` | Install a skill from GitHub or local path |
| `asm skill list` | List skills registered in the workspace |
| `asm skill analyze <name> --local` | Analyze one local skill with OpenAI using `ASM_LLM_MODEL` and `OPENAI_API_KEY` |
| `asm skill analyze <name> --cloud` | Submit one local skill to the optional ASM cloud analyzer |
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
| `asm create expertise <name> <skills...>` | Bundle skills into a task-oriented domain |
| `asm expertise list` | List expertises defined in the workspace |
| `asm expertise skills <name>` | List skills in an expertise |
| `asm expertise suggest <task>` | Match a task to existing expertises (semantic) |
| `asm expertise auto <task>` | Autonomous match/create and configuration |
| `asm expertise eval --dataset <file>` | Evaluate routing quality (top-1/top-k/MRR) and enforce gates |
| `asm --version` | Print version |

## Development

```bash
git clone https://github.com/gil-kapel/asm.git
cd asm
uv sync
uv run asm --version
```

Build release wheel artifacts:

```bash
./scripts/build-wheel.sh
```

This generates:
- `dist/release/asm-<version>-py3-none-any.whl` (versioned artifact)
- `dist/release/asm-py3-none-any.whl` (stable release asset name used by installer/update)

**Docs & GitHub Pages**

- Local: `uv sync --extra docs && uv run mkdocs serve` → http://127.0.0.1:8000
- Publish to GitHub Pages: push to `main` runs [`.github/workflows/deploy-docs.yml`](.github/workflows/deploy-docs.yml) and deploys the built site. **One-time:** Repo → **Settings** → **Pages** → **Build and deployment** → Source: **GitHub Actions**. Site URL: `https://<user>.github.io/asm/` (or your custom domain if set in Pages settings).

The CLI entry point is `src/asm/cli/__init__.py`, registered as `asm` via `pyproject.toml`:

```toml
[project.scripts]
asm = "asm.cli:cli"
```
