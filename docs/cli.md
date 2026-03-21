---
title: CLI reference
---

# CLI reference

ASM exposes a single entrypoint, `asm`, with subcommands grouped by workflow. For options and examples, run any command with `--help` (e.g. `asm expertise --help`).

## Workspace

| Command | Description |
|---------|-------------|
| `asm init` | Initialise an ASM workspace (`asm.toml` + `.asm/`). |
| `asm sync` | Install missing skills, verify integrity, and sync agent configs. |

## Discovery and skills

| Command | Description |
|---------|-------------|
| `asm search <query>` | Federated discovery across curated registries and providers. |
| `asm add skill <source>` | Install a skill from GitHub, Smithery, Playbooks, or a local path. |
| `asm skill list` | List skills registered in the workspace. |
| `asm skill analyze <name> --cloud` | Submit one local skill to the ASM cloud analyzer and store the latest scorecard under `.asm/analysis/`. |
| `asm skill analyze <name> --local` | Analyze one local skill with LiteLLM using `ASM_LLM_MODEL` and a provider API key. |
| `asm create skill <name> <desc>` | Scaffold a new skill package, optionally with `--ai`, `--github-search`, or iterative `--loop` refinement. |
| `asm skill share <name>` | Package one local skill into `dist/skills/` as a folder plus zip archive for publishing or reuse. |
| `asm skill commit <name> -m <msg>` | Commit local changes of a skill. |
| `asm skill stash push` / `apply` | Save or restore WIP snapshots. |
| `asm skill tag` / `checkout` / `history` / `status` / `diff` | Manage and inspect skill versions. |

## Cloud analyzer

`asm skill analyze` supports two explicit modes and does not affect local/offline ASM flows outside analysis itself.

## Iterative skill creation

`asm create skill` can run a local build/analyze/rewrite loop when you want ASM to keep improving the draft before it finishes.

```bash
asm create skill sqlmodel-database "Async SQLModel patterns" --loop
asm create skill sqlmodel-database "Async SQLModel patterns" --loop --target-score 0.9 --max-tries 5
```

`--loop` uses the same LiteLLM setup as `--ai` and local analysis:

- `ASM_LLM_MODEL` or `--model`
- a provider API key such as `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`

When enabled, ASM:

- generates the initial `SKILL.md`
- runs local analysis to get a scorecard
- if the scorecard indicates weak trigger routing or evidence grounding, automatically fetches DeepWiki/GitHub evidence and materializes it into `references/research-iteration-<n>.md`
- feeds the scorecard `improvement_prompt` back into the writer
- stops once the aggregate 0-1 score reaches `--target-score` or `--max-tries` is reached

## GitHub repo enrichment

`asm create skill` can also search GitHub for relevant repositories and use the top matches as extra generation context.

```bash
asm create skill sqlmodel-database "Async SQLModel patterns" --github-search "sqlmodel fastapi async"
asm create skill sqlmodel-database "Async SQLModel patterns" --github-search "sqlmodel fastapi async" --github-search-limit 2
```

This path:

- searches GitHub repositories by stars
- selects the top matches
- reuses the DeepWiki repo fetcher to collect README, structure, docs, and key source files
- sends the combined bundle into the LLM skill writer

## Share a skill

ASM includes a core packaging path for user-authored skills so they can be shared outside the current workspace.

```bash
asm skill share langgraph-skill-builder
asm skill share langgraph-skill-builder --overwrite
asm skill share langgraph-skill-builder --out ./dist/public-skills --overwrite
```

This command creates:

- a share folder under `dist/skills/<name>/`
- a zip archive at `dist/skills/<name>.zip`
- a `share.json` manifest with description, version, integrity, snapshot, and file inventory

### Command

```bash
asm skill analyze my-skill --cloud
asm skill analyze my-skill --local
asm skill analyze my-skill --local --model openai/gpt-5-mini
asm skill analyze my-skill --cloud --api-url http://127.0.0.1:8000
```

### Local mode

`--local` uses LiteLLM on the current machine. It requires:

- `ASM_LLM_MODEL` or `--model`
- a provider API key such as `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`

Example user-level config:

```bash
mkdir -p ~/.asm-cli
cat >> ~/.asm-cli/.env <<'EOF'
ASM_LLM_MODEL=openai/gpt-5-mini
OPENAI_API_KEY=sk-...
EOF
```

### Cloud mode

- `ASM_CLOUD_API_URL`: base URL for the managed analyzer, for example `https://api.asm.dev` or `http://127.0.0.1:8000`
- `ASM_CLOUD_API_KEY`: optional bearer token for managed deployments

Recommended user-level config:

```bash
mkdir -p ~/.asm-cli
cat >> ~/.asm-cli/.env <<'EOF'
ASM_CLOUD_API_URL=http://127.0.0.1:8000
ASM_CLOUD_API_KEY=dev-token
EOF
```

ASM loads user-level env files automatically on startup:

- `~/.asm-cli/.env`
- `~/.config/asm/env`
- `~/.config/asm/.env`

### Local artifact storage

Each cloud analysis stores the latest project-visible artifact here:

- `.asm/analysis/<skill>/latest.json`
- `.asm/analysis/<skill>/manifest.json`

The saved artifact includes the returned scorecard, embedding profile, local snapshot id, and integrity hash.

### Running the backend locally

Install the optional cloud extra and run the MVP backend:

```bash
uv sync --extra cloud
uv run uvicorn backend.api:app --reload
```

Optional backend storage location:

- `ASM_CLOUD_STORE`: directory used by the backend to persist scorecards and manifest corpus

## Expertises

Agents use expertises to decide which skills to load for a task; these commands configure and evaluate that routing.

| Command | Description |
|---------|-------------|
| `asm create expertise <name> <skills...>` | Bundle skills into a task-oriented expertise. |
| `asm expertise list` | List expertises defined in the workspace. |
| `asm expertise skills <name>` | List skills in an expertise. |
| `asm expertise suggest <task>` | Match a natural-language task to existing expertises. |
| `asm expertise auto <task>` | Autonomous match/create, install missing skills, and sync. |
| `asm expertise eval --dataset <file>` | Run routing benchmarks and enforce quality gates. |

## Lockfile and updates

| Command | Description |
|---------|-------------|
| `asm lock migrate` | Migrate `asm.lock` entries to the current schema. |
| `asm update` | Update ASM from the official release wheel (fallback to git). |

## Getting help

```bash
asm --help
asm expertise --help
asm add skill --help
```

## Shell completion

ASM uses Click shell completion, so command names, flags, and dynamic workspace values can autocomplete.

Dynamic completion currently includes:

- installed skill names for `asm skill ...`
- expertise names for `asm expertise skills ...`
- snapshot/tag refs for `asm skill checkout ...`
- stash ids for `asm skill stash apply ...`

### Zsh

```bash
echo 'eval "$(_ASM_COMPLETE=zsh_source asm)"' >> ~/.zshrc
source ~/.zshrc
```

### Bash

```bash
echo 'eval "$(_ASM_COMPLETE=bash_source asm)"' >> ~/.bashrc
source ~/.bashrc
```

### Fish

```bash
mkdir -p ~/.config/fish/completions
_ASM_COMPLETE=fish_source asm > ~/.config/fish/completions/asm.fish
```
