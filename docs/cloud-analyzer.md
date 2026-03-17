---
title: Cloud analyzer
---

# Cloud analyzer

ASM Cloud MVP adds one managed capability first: cloud skill analysis.

The local CLI stays local-first and fully usable offline. Analysis now has two explicit modes:

```bash
asm skill analyze <name> --local
asm skill analyze <name> --cloud
```

- `--local`: run LLM-backed analysis on the user's machine with `ASM_LLM_MODEL` and a provider API key
- `--cloud`: send the packaged skill to the managed backend

## What the cloud does

The MVP backend handles only:

- skill analysis
- embedding-backed similarity for analysis/ranking
- scorecard storage

It does not yet handle:

- marketplace publishing
- telemetry pipelines
- full evaluator/release gates
- enterprise features

## API surface

The current MVP backend exposes:

- `GET /health`
- `GET /healthz`
- `POST /v1/skills/analyze`
- `GET /v1/skills/analyses/{analysis_id}`

`POST /v1/skills/analyze` accepts:

- structured `SkillManifest`
- `SkillEvidence`
- `EmbeddingProfile`
- transmitted skill files

It returns:

- `analysis_id`
- `analysis_version`
- `scorecard`
- `embedding_profile`

## Scorecard fields

The analyzer returns these core fields:

- `trigger_specificity`
- `novelty`
- `evidence_grounding`
- `duplication_risk`
- `status`

And these support fields:

- `findings`
- `recommended_actions`
- `similar_skills`

## Local storage

ASM keeps the latest returned analysis in the project so cloud use stays inspectable and optional.

Stored files:

- `.asm/analysis/<skill>/latest.json`
- `.asm/analysis/<skill>/manifest.json`

The saved artifact includes:

- submitted manifest
- evidence inventory
- returned scorecard
- embedding profile
- local `snapshot_id`
- local integrity hash

## Configuration

### Local analysis config

For `--local`, configure a LiteLLM model plus a provider key:

```bash
mkdir -p ~/.asm-cli
cat >> ~/.asm-cli/.env <<'EOF'
ASM_LLM_MODEL=openai/gpt-5-mini
OPENAI_API_KEY=sk-...
EOF
```

Example:

```bash
asm skill analyze my-skill --local
asm skill analyze my-skill --local --model anthropic/claude-3-5-sonnet
```

### Cloud analysis config

Set the analyzer URL and optional API key in a user-level env file:

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

You can also override the URL per command:

```bash
asm skill analyze my-skill --cloud --api-url http://127.0.0.1:8000
```

### Backend-side config

- `ASM_CLOUD_STORE`: directory where the backend stores analyses and manifest corpus
- `ASM_CLOUD_ANALYZER_VERSION`: optional version string for the analyzer response

## Running the MVP backend locally

Install the optional backend dependencies:

```bash
uv sync --extra cloud
```

Run the FastAPI app:

```bash
uv run uvicorn backend.api:app --reload
```

Set a custom backend storage directory if needed:

```bash
export ASM_CLOUD_STORE="$HOME/.asm-cloud-dev"
uv run uvicorn backend.api:app --reload
```

## Embedding provenance

The MVP now carries an explicit `EmbeddingProfile` with:

- provider
- model
- dimension
- normalization flag
- distance metric
- embedding version
- analysis mode

This profile is stored with each scorecard so future routing and analysis results stay explainable.
