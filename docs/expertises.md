---
title: Expertises and routing
---

# Expertises and routing

Expertises are the **primary routing layer** in ASM: agents choose one expertise for a task, then load only that group’s skills in dependency order. Skills are the units inside expertises.

## Why expertises

- **Autonomous selection:** Agents match your task to one expertise group (e.g. “db-layer”, “cli-engineering”) instead of scanning every skill.
- **One group at a time:** Only the skills in the chosen expertise are loaded, so context stays focused and dependency order is respected.
- **No skill soup:** Without expertises, agents would see a flat list of skills; with expertises, they see task-oriented bundles with clear relationships.

## How routing works

1. The agent reads **`.asm/main_asm.md`** first (the root index).
2. **main_asm.md** lists the **Expertise Group Router**: a table of groups with purpose, task signals, and navigation to each group’s index.
3. The agent **selects one expertise group** that matches the task (using the selection rubric in main_asm.md).
4. It opens that group’s **`.asm/expertises/<group>/index.md`** and **`relationships.md`**.
5. It loads **only the skills** listed for that group, in the order defined by relationships.

See your project’s `.asm/main_asm.md` after running `asm sync` for the exact router and active expertises.

## CLI at a glance

| Command | Description |
|---------|-------------|
| `asm expertise suggest "<task>"` | Match a natural-language task to existing expertises (semantic similarity). |
| `asm expertise auto "<task>"` | Match or create an expertise, install missing skills, and sync agent config. |
| `asm create expertise <name> <skills...> --desc "..."` | Bundle skills into a new task-oriented expertise. |
| `asm expertise eval --dataset <file>` | Run routing benchmarks and enforce quality gates (e.g. min top-1 accuracy). |

Full options: [CLI reference](cli.md).

## Creating and editing expertises

To define a new expertise, use `asm create expertise` with a name, the list of skill names to bundle, and a description. To change which skills are in an expertise, edit the generated files under `.asm/expertises/<name>/` and the `[expertises]` section in `asm.toml`, or use the CLI.

For step-by-step “bundling” and examples, see [Authoring skills](skills/authoring.md#bundling-expertises).
