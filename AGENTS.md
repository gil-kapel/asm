# AGENTS.md

## Cursor Cloud specific instructions

**Product**: ASM (Agent Skill Manager) — a Python CLI tool that manages agent skills in a project-local `.asm/` directory and syncs them into Cursor/Claude/Codex configs.

**Stack**: Python 3.14, Click CLI, uv package manager, hatchling build system. No databases or background services — file-based state only.

### Running the CLI

- Always use `uv run asm <command>` to run the CLI (never `python` directly).
- For editable development installs: `uv tool install --editable .`
- See `README.md` for all CLI commands and usage.

### Testing

- Run tests: `uv run pytest`
- Run with coverage: `uv run pytest --cov=src/asm`
- The `test` extra provides pytest, pytest-cov, pytest-asyncio.
- Note: `tests/test_update.py::test_update` has a pre-existing failure (assertion mismatch on subprocess call count).

### Linting

- No linter is configured in `pyproject.toml`. Use `uvx ruff check src/` for ad-hoc linting.

### Optional dependencies

- `asm[llm]` adds LiteLLM for AI-powered skill creation and semantic search. Requires `OPENAI_API_KEY` (or another LLM provider key).
- Without an API key, the CLI still works — embedding search falls back to BLAKE2b hash-based pseudo-embeddings.
