# ASM — Agent Skill Manager


<p align="center">
  <img src="assets/asm-logo.svg" alt="ASM logo" width="250" />
</p>

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![CLI Click](https://img.shields.io/badge/cli-click-0ea5e9)](https://click.palletsprojects.com/)
[![Package Manager uv](https://img.shields.io/badge/package_manager-uv-7c3aed)](https://docs.astral.sh/uv/)

ASM manages a project-local `.asm/` skill graph and syncs it into Cursor / Claude / Codex.

- **Curated Index**: Access verified, high-quality skills with non-obvious knowledge and actionable patterns.
- **Semantic Search**: Native embedding-based ranking (LiteLLM/OpenAI) with local caching for sub-second relevance.
- **Expertise Layer**: Bundle skills into task-oriented domains for autonomous agent selection and auto-configuration.
- **Advanced Skill Creation**: Distill complex patterns from GitHub repos (README, source, structure) using AI.
- **Lock Reproducibility**: Pin SHA-256 integrity hashes in `asm.lock` for consistent environments.
- **Zero-Touch Sync**: Automatically update agent context whenever skills or expertises change.

[Quick Start](#quick-start) · [Usage](#usage) · [Agent Integration](#agent-integration) · [CLI Reference](#cli-reference)

## Copy Prompt For Your Agent

```text
Set up ASM in this project end-to-end.

ASM CLI (Agent Skill Manager) is a project-local skill orchestrator: it installs curated agent skills into `.asm/`, builds a root index (`.asm/main_asm.md`), and syncs those skills into the active agent config (Cursor/Claude/Codex).

1) Install ASM:
   curl -LsSf https://raw.githubusercontent.com/gil-kapel/asm/main/install.sh | sh

2) Initialize ASM in the current project root:
   asm init

3) (Optional) Configure SkillsMP/LLM access at user level:
   - set `SKILLSMP_API_KEY` or `OPENAI_API_KEY` in ~/.asm-cli/.env for semantic discovery and AI skill creation.

4) Discover and install the most relevant curated skills:
   - run `asm search <query>` to find verified skills (marked [curated])
   - run `asm add skill <source>` for each selected skill

5) Automate expertise configuration for your task:
   - describe what you want to do in natural language
   - run `asm expertise auto "<task description>"`
   - ASM will autonomously match your task to expertise bundles, install missing skills, and sync your agent context.

6) Sync integrations:
   asm sync

7) Output:
   - list installed skills and active expertises
   - confirm which agent integration was synced
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

### Search curated and federated registries

```bash
# Search across curated index and healthy providers
asm search "database patterns"

# Limit result size
asm search "frontend design" --limit 5
```

ASM performs federated discovery across available providers (ASM index, Smithery, Playbooks, GitHub, SkillsMP).
- **[curated]**: Verified skills with quality scoring rank first.
- **Semantic Ranking**: Query embeddings (via LiteLLM) are matched against skill triggers for high relevance.
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

# Create from a local module
asm create skill auth-utils "Project auth conventions" --from ./src/auth/ --ai
```

- **`--from-repo OWNER/REPO`**: Fetches the README, directory structure, and key source files via GitHub API as context for the LLM.
- **`--ai`**: Use LiteLLM to generate sophisticated instructions, usage guidelines, and examples.
- **`--from ./path`**: Analyzes local code to extract internal patterns and conventions.

### AI-assisted skill creation (LiteLLM)

ASM can generate SKILL.md content (Instructions, Usage, Examples) using an LLM via [LiteLLM](https://github.com/BerriAI/litellm). Install the optional extra and set a provider API key:

```bash
uv pip install asm[llm]
export OPENAI_API_KEY=sk-...   # or ANTHROPIC_API_KEY, etc.
```

Create a skill with generated content:

```bash
asm create skill pdf-helper "Extract text and tables from PDFs" --ai
asm create skill cli-ux "CLI UX patterns for Click" --ai --model anthropic/claude-3-5-sonnet
```

- **`--ai`**: Use LiteLLM to generate the skill description and body.
- **`--model`**: LiteLLM model string (default: `openai/gpt-4o-mini`). Can be set with `ASM_LLM_MODEL`.
- **`--from ./path`**: Local file or directory; the LLM receives its content as context.
- **`--from-url URL`**: Fetch content from a URL and use it as context for the LLM. Supports GitHub API contents (e.g. `https://api.github.com/repos/owner/repo/contents/README.md?ref=main`) and raw URLs; directories are expanded by fetching each file.

LiteLLM supports 100+ providers (OpenAI, Anthropic, Gemini, Bedrock, etc.) with a single interface; set the corresponding API key and use the `provider/model-name` format for `--model`.

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
| `asm create expertise <name> <skills...>` | Bundle skills into a task-oriented domain |
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

The CLI entry point is `src/asm/cli/__init__.py`, registered as `asm` via `pyproject.toml`:

```toml
[project.scripts]
asm = "asm.cli:cli"
```
