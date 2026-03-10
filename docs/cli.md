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
| `asm create skill <name> <desc>` | Scaffold a new skill package (optionally from code or with `--ai`). |
| `asm skill commit <name> -m <msg>` | Commit local changes of a skill. |
| `asm skill stash push` / `apply` | Save or restore WIP snapshots. |
| `asm skill tag` / `checkout` / `history` / `status` / `diff` | Manage and inspect skill versions. |

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
