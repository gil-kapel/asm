# ASM — Next Steps (high level)

High-level feature ideas by category. Prioritise as needed.

---

## Discovery & registry
- **Expertise bundles** — `asm create expertise <skills...> --desc <desc>` (already in CLI ref as coming soon).
- **Search ranking** — Use repo context (e.g. `--path`) to rank results by relevance to current project.
- **New providers** — Add or plug in more skill sources beyond GitHub, Smithery, Playbooks, SkillsMP.
- **Offline / cache** — Cache search results or provider responses for offline or rate-limit resilience.

---

## Skill lifecycle
- **Remove / uninstall** — `asm remove skill <name>` and prune from asm.toml + asm.lock.
- **Upgrade skills** — Refresh from source (e.g. `asm skill upgrade <name>`) and update lock.
- **Skill metadata** — Optional version, author, or tags in SKILL.md frontmatter for display and filtering.

---

## Sync & integrations
- **More agents** — Support additional IDEs or agents beyond Cursor, Claude Code, Codex.
- **Sync dry-run** — Preview what would be written to agent configs before applying.
- **Selective sync** — Sync only a subset of skills (e.g. by tag or expertise) into an agent.

---

## DX & CLI
- **Structured output** — JSON/JSONL for `asm search` or `asm skill status` for scripting.
- **Quieter mode** — Less noise for CI or scripts (e.g. `--quiet` or `ASM_QUIET=1`).
- **Better errors** — Clear messages and remediation hints for lock/sync/network failures.
- **Docs** — In-repo docs (e.g. `docs/`) for sync lifecycle, lock schema, provider contract.

---

## Reliability & ops
- **Tests** — Unit and integration tests for core flows (init, add, sync, lock).
- **Lock migrations** — Keep `asm lock migrate` in sync with schema changes; document versions.
- **Health check** — `asm doctor` or similar: env, writable paths, provider reachability.

---

## Ecosystem & sharing
- **Publish / share** — Publish a skill or expertise bundle to a registry (e.g. Smithery, GitHub template).
- **Team workflows** — Document or support “base asm.toml + overlay” or shared expertise for teams.
- **CI integration** — Example workflows (e.g. GitHub Actions) for `asm sync` in CI or pre-commit.
