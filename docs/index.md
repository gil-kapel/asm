---
title: ASM — Agent Skill Manager
---

# ASM — Agent Skill Manager

**ASM is a project-local Agent Skill Manager:** it installs curated skills into `.asm/`, bundles them into task-oriented expertises, builds a root index (`.asm/main_asm.md`), and syncs into your active agent configs (Cursor, Claude, Codex, GitHub Copilot).

## Prompt for agents

Copy this into your agent (Cursor, Claude Code, Codex, GitHub Copilot) to set up ASM end-to-end:

```text
Set up ASM in this project and leave it in a working state.

ASM CLI (Agent Skill Manager) installs curated skills into `.asm/`, builds `.asm/main_asm.md`, configures expertises, and syncs the router into the active agent config.

Do this in order:

1. Check whether `asm` is already installed. Install it only if missing:
   `curl -LsSf https://raw.githubusercontent.com/gil-kapel/asm/main/install.sh | sh`

2. Check whether this repo already has ASM initialized.
   - If `asm.toml` does not exist, run `asm init`.
   - If it already exists, keep the current workspace and continue.

3. Inspect the project briefly and choose a few relevant search queries.
   - Prefer curated, project-specific skills.
   - Avoid installing a long list of generic skills.

4. Install the best matching skills:
   - `asm search "<query>"`
   - `asm add skill <source>`

5. Configure expertise routing for the actual task or project stack:
   - `asm expertise auto "<task description>"`

6. Sync integrations:
   - `asm sync`

7. If `ASM_CLOUD_API_URL` is configured and a local skill is available, run one cloud analysis:
   - `asm skill analyze <skill-name> --cloud`

8. At the end, report:
   - whether ASM was installed or already present
   - whether the workspace was initialized or already initialized
   - which skills were installed
   - which expertise was selected or created
   - which agent config(s) were synced
   - whether cloud analysis was run and where the scorecard was saved
```

## How it fits together

![ASM overview: config → workspace → agents](assets/asm-overview.png)

- **asm.toml** declares which skills are active and their sources; **asm.lock** pins integrity hashes.
- **.asm/expertises/** defines task-oriented bundles; **.asm/main_asm.md** is the root index agents read first; **.asm/skills/** holds each skill package.
- Agents **route by expertise first** (choose one group from `main_asm.md`), then load that group’s skills.
- **Sync** (e.g. `asm sync`) updates the workspace and agent configs from config.

## What you can do here

| Goal | Where to go |
|------|-------------|
| Get up and running quickly | [Getting started](getting-started.md) |
| Configure optional cloud skill analysis | [Cloud analyzer](cloud-analyzer.md) |
| Configure expertises and route by task | [Expertises](expertises.md) |
| See every command and option | [CLI reference](cli.md) |
| Author or bundle skills | [Authoring skills](skills/authoring.md) |
| See what changed by version | [Release notes](releases/index.md) |

## Quick path to “it works”

1. **Install:** `curl -LsSf …/install.sh | sh` or `uv tool install …`
2. **Initialise:** `asm init` in your project root.
3. **Add skills:** `asm search "<query>"` then `asm add skill <source>`.
4. **Match task to an expertise:** `asm expertise auto "<task description>"` so agents know which skills to use.
5. **Sync:** `asm sync` to install missing skills and update agent configs.

For the full pitch and more examples, see the [README on GitHub](https://github.com/gil-kapel/asm).
