"""LLM-backed generation for skill content.

Uses LiteLLM for completions (required dependency).
Provides a robust client with centralized configuration and error handling.
"""

from __future__ import annotations

import json
import logging
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, List, Optional, Tuple, TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_MODEL = "openai/gpt-4o-mini"
DEFAULT_MAX_TOKENS = 4096
BODY_DELIMITER = "---BODY---"
StructuredModelT = TypeVar("StructuredModelT", bound=BaseModel)
_JS_SCRIPT_SUFFIXES = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}


class LLMError(Exception):
    """Base class for all LLM-related errors."""


class ProviderError(LLMError):
    """Raised when the LLM provider returns an error."""


class ParsingError(LLMError):
    """Raised when the LLM response cannot be parsed correctly."""


class LLMClient:
    """A robust client for LLM operations via LiteLLM."""

    def __init__(self, model: Optional[str] = None):
        """Initialize the client, ensuring LiteLLM is available."""
        self._ensure_litellm()
        self.model = (model or os.environ.get("ASM_LLM_MODEL") or DEFAULT_MODEL).strip()

    def _ensure_litellm(self) -> None:
        """Check for LiteLLM and provide a helpful error if missing."""
        try:
            import litellm  # noqa: F401
        except ImportError as e:
            raise LLMError(
                "LLM support requires litellm. Reinstall asm: uv tool install asm or pip install -U asm"
            ) from e

    def _completion_response(
        self,
        messages: List[dict[str, str]],
        max_tokens: int = DEFAULT_MAX_TOKENS,
        num_retries: int = 2,
        **kwargs: Any,
    ) -> Any:
        """Execute a chat completion and return the raw provider response."""
        import litellm

        try:
            logger.debug("Executing LLM completion with model: %s", self.model)
            return litellm.completion(
                model=self.model,
                messages=messages,
                max_tokens=max_tokens,
                num_retries=num_retries,
                **kwargs,
            )
        except Exception as e:
            logger.error("LLM completion failed: %s", e)
            raise ProviderError(f"LLM provider error: {e}") from e

    def completion(
        self,
        messages: List[dict[str, str]],
        max_tokens: int = DEFAULT_MAX_TOKENS,
        num_retries: int = 2,
        **kwargs: Any,
    ) -> str:
        """Execute a chat completion with error handling and logging."""
        response = self._completion_response(
            messages=messages,
            max_tokens=max_tokens,
            num_retries=num_retries,
            **kwargs,
        )
        return self._extract_response_text(response).strip()

    def completion_pydantic(
        self,
        messages: List[dict[str, str]],
        *,
        response_model: type[StructuredModelT],
        schema_name: str = "asm_structured_output",
        max_tokens: int = DEFAULT_MAX_TOKENS,
        num_retries: int = 2,
    ) -> StructuredModelT:
        """Execute a completion that should validate into one Pydantic model."""
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": True,
                "schema": _strict_json_schema(response_model.model_json_schema()),
            },
        }

        try:
            response = self._completion_response(
                messages=messages,
                max_tokens=max_tokens,
                num_retries=num_retries,
                response_format=response_format,
            )
        except ProviderError:
            logger.warning("Structured output unavailable for model %s; retrying with plain JSON prompt.", self.model)
            response = self._completion_response(
                messages=messages,
                max_tokens=max_tokens,
                num_retries=num_retries,
            )
        return self._parse_pydantic_response(response, response_model)

    def generate_skill_content(
        self,
        name: str,
        description: str,
        source_context: Optional[str] = None,
        *,
        supporting_files: Optional[list[str]] = None,
    ) -> Tuple[str, str]:
        """Generate SKILL.md content using structured prompts and robust parsing."""
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(
            name,
            description,
            source_context,
            supporting_files=supporting_files,
        )

        content = self.completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        )

        if not content:
            logger.warning("LLM returned empty content for skill: %s", name)
            return description, self._fallback_body(name, description)

        return self._parse_skill_response(content, description)

    def revise_skill_content(
        self,
        name: str,
        current_skill_md: str,
        improvement_prompt: str,
        *,
        supporting_files: Optional[list[str]] = None,
    ) -> Tuple[str, str]:
        """Rewrite an existing skill using structured improvement guidance."""
        runtime_preference = infer_runtime_preference(
            text_blobs=[current_skill_md, improvement_prompt],
            supporting_files=supporting_files,
        )
        runtime_guidance = render_runtime_guidance(runtime_preference)
        system_prompt = (
            "You are improving an existing ASM skill package.\n"
            "- Preserve the skill's purpose, but rewrite it to improve routing precision, evidence grounding, and distinctness.\n"
            "- Keep SKILL.md short and scannable.\n"
            "- Do not inline full API contracts, long examples, or exhaustive docs inside SKILL.md.\n"
            "- Prefer referencing files that already exist under references/, examples/, scripts/, or assets/ using explicit relative paths (e.g. `references/foo.md`).\n"
            f"{runtime_guidance}"
            "- Update the `## Do Not Select This Skill When` / boundary section so it explicitly mentions the nearby skills by name (the improvement prompt includes them) and clearly explains why this skill should not be chosen instead.\n"
            "- The rewritten body MUST include a `## Niche Examples` section with 2-3 short concrete mini-examples (each 3-6 lines) demonstrating how to use the skill correctly.\n"
            "- In the returned one-line description (frontmatter `description:`), include 3-5 trigger phrases as explicit double-quoted strings.\n"
            "- Those exact quoted strings must be the routing trigger phrases that ASM will extract for `trigger_phrases`.\n"
            "- Output only valid markdown.\n"
            "- Return a one-line description, then the delimiter, then the full markdown body.\n"
            f"- Use exactly '{BODY_DELIMITER}' on its own line between description and body."
        )
        support_block = self._format_supporting_files(supporting_files)
        user_prompt = (
            f"Skill name: {name}\n\n"
            f"Current SKILL.md:\n\n{current_skill_md[:20000]}\n\n"
            f"Improvement prompt:\n\n{improvement_prompt}\n\n"
            f"Runtime preference: {runtime_preference}\n\n"
            f"{support_block}\n\n"
            "Target shape for SKILL.md:\n"
            "- one short purpose paragraph\n"
            "- compact selection guidance\n"
            "- short workflow or rules\n"
            "- a `## Niche Examples` section with 2-3 short concrete mini-examples (each 3-6 lines)\n"
            "- a supporting files section that points to detailed docs in the skill directory\n\n"
            f"Respond with:\n1. A one-line description\n2. {BODY_DELIMITER}\n3. The full markdown body"
        )
        content = self.completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        )
        if not content:
            raise ParsingError("LLM returned empty content while revising a skill.")
        return self._parse_skill_response(content, name.replace("-", " "))

    def generate_support_file_content(
        self,
        skill_name: str,
        current_skill_md: str,
        relative_path: str,
        *,
        niche_examples: str = "",
        supporting_files: Optional[list[str]] = None,
    ) -> str:
        """Generate one concrete support file for a skill package."""
        runtime_preference = infer_runtime_preference(
            text_blobs=[current_skill_md, niche_examples, relative_path],
            supporting_files=supporting_files,
        )
        runtime_guidance = render_runtime_guidance(runtime_preference)
        system_prompt = (
            "You are writing one concrete support file for an ASM skill package.\n"
            "- Write ONLY the file contents for the requested target path.\n"
            "- Do not wrap the answer in markdown fences.\n"
            "- Do not write placeholders, TODOs, or meta commentary.\n"
            "- The file must be specific to the skill and usable as-is.\n"
            "- If the target is markdown, include concrete commands, inputs, outputs, and artifact names.\n"
            "- If the target is a shell script, make it executable-style bash and do real work, even if minimal.\n"
            "- If the target is a python script, make it a minimal runnable CLI using argparse.\n"
            "- If the target is JSON, return valid JSON only.\n"
            f"{runtime_guidance}"
            "- Use the current SKILL.md and niche examples as the source of truth."
        )
        support_block = self._format_supporting_files(supporting_files)
        user_prompt = (
            f"Skill name: {skill_name}\n\n"
            f"Target file path: {relative_path}\n\n"
            f"Runtime preference: {runtime_preference}\n\n"
            f"Current SKILL.md:\n\n{current_skill_md[:20000]}\n\n"
            f"Niche examples:\n\n{niche_examples[:8000] or '(none)'}\n\n"
            f"{support_block}\n\n"
            "Return only the file contents for the target path."
        )
        content = self.completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        )
        if not content:
            raise ParsingError(f"LLM returned empty content for support file: {relative_path}")
        return self._clean_support_file_response(content)

    def _build_system_prompt(self) -> str:
        return (
            "You are an expert at writing agent skills in SKILL.md format.\n"
            "- If source context is provided, you MUST distill it into specific Instructions and Usage.\n"
            "- Keep SKILL.md short, high-signal, and easy to route on.\n"
            "- Do not dump full research notes, schemas, or long examples into SKILL.md.\n"
            "- Put detailed material in files under references/, examples/, scripts/, or assets/, and point to those files from SKILL.md using explicit relative paths (e.g. `references/foo.md`).\n"
            "- Output only valid markdown.\n"
            "- The description must be one line, third person, summarizing what the skill does and its triggers.\n"
            "- The body should stay compact and include clear routing guidance plus a supporting-files section.\n"
            "- The body MUST include a `## Niche Examples` section with 2-3 short concrete mini-examples (each 3-6 lines) demonstrating how to use the skill correctly.\n"
            f"- You MUST separate the description and the body with exactly '{BODY_DELIMITER}' on its own line."
        )

    def _build_user_prompt(
        self,
        name: str,
        description: str,
        source_context: Optional[str],
        *,
        supporting_files: Optional[list[str]] = None,
    ) -> str:
        runtime_preference = infer_runtime_preference(
            text_blobs=[name, description, source_context or ""],
            supporting_files=supporting_files,
        )
        parts = [
            f"Skill name: {name}",
            f"Initial description: {description}",
            f"Runtime preference: {runtime_preference}",
            self._format_supporting_files(supporting_files),
        ]
        if source_context:
            # Truncate context to stay within common limits while leaving room for the response
            parts.append(f"Source context:\n\n{source_context[:15000]}")

        parts.append(
            "Target shape for SKILL.md:\n"
            "- one short purpose paragraph\n"
            "- `## Select This Skill When`\n"
            "- `## Do Not Select This Skill When`\n"
            "- `## Workflow` or `## Rules`\n"
            "- `## Niche Examples` with 2-3 short concrete mini-examples (each 3-6 lines)\n"
            "- `## Supporting Files` with links to real files in the skill directory\n"
            "- keep the file compact; do not inline long API contracts or verbose examples"
        )
        parts.append(
            f"Respond with:\n1. A one-line description\n2. {BODY_DELIMITER}\n3. The full markdown body"
        )
        return "\n\n".join(parts)

    def _format_supporting_files(self, supporting_files: Optional[list[str]]) -> str:
        """Render the support-file list for prompts."""
        if not supporting_files:
            return (
                "Supporting files already in the skill directory:\n"
                "- none yet; if the skill needs detailed docs, mention the standard folders (`references/`, `examples/`, `scripts/`) briefly instead of inlining everything"
            )
        files = "\n".join(f"- {path}" for path in supporting_files[:20])
        return f"Supporting files already in the skill directory:\n{files}"

    def _parse_skill_response(self, content: str, default_desc: str) -> Tuple[str, str]:
        """Parse the LLM response, handling various output formats."""
        if BODY_DELIMITER in content:
            parts = content.split(BODY_DELIMITER, 1)
            desc = self._clean_description(parts[0]) or default_desc
            body = parts[1].strip()
            return desc, body

        # If delimiter is missing, try to split by the first header
        header_match = re.search(r"^#+ ", content, re.MULTILINE)
        if header_match:
            desc_part = content[: header_match.start()].strip()
            body_part = content[header_match.start() :].strip()
            desc = self._clean_description(desc_part) or default_desc
            return desc, body_part

        # Last resort: use the first line as description and everything as body
        lines = content.splitlines()
        first_line = lines[0].strip()
        if len(first_line) < 150:
            return self._clean_description(first_line) or default_desc, content

        return default_desc, content

    def _clean_description(self, text: str) -> str:
        """Clean up the description part of the response."""
        # Remove "Description:", "Part 1:", markdown headers, quotes, etc.
        text = re.sub(r"^(description|part\s*1):", "", text, flags=re.IGNORECASE).strip()
        text = text.lstrip("#").strip()
        # Avoid stripping quotes that belong to routing trigger phrases.
        # We only remove a single outer quote pair if the whole description is wrapped.
        text = text.split("\n")[0].strip()
        if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
            text = text[1:-1].strip()
        return text

    def _fallback_body(self, name: str, description: str) -> str:
        title = name.replace("-", " ").title()
        return (
            f"# {title}\n\n"
            f"## Instructions\n\n{description}\n\n"
            "## Usage\n\nUse when the task matches the description above.\n"
        )

    def _clean_support_file_response(self, content: str) -> str:
        """Remove accidental code fences around full-file responses."""
        text = content.strip()
        fence_match = re.match(r"^```[A-Za-z0-9_-]*\n(?P<body>.*)\n```$", text, re.DOTALL)
        if fence_match:
            return fence_match.group("body").strip() + "\n"
        return text if text.endswith("\n") else text + "\n"

    def _extract_response_text(self, response: Any) -> str:
        """Extract the most useful text payload from a provider response."""
        message = response.choices[0].message
        content = getattr(message, "content", None)
        if isinstance(content, str) and content.strip():
            return content
        if isinstance(content, list):
            text_parts: list[str] = []
            for part in content:
                if isinstance(part, str) and part.strip():
                    text_parts.append(part)
                elif isinstance(part, dict):
                    text = part.get("text") or part.get("content")
                    if isinstance(text, str) and text.strip():
                        text_parts.append(text)
            if text_parts:
                return "\n".join(text_parts)
        parsed = getattr(message, "parsed", None)
        if parsed is not None:
            if isinstance(parsed, BaseModel):
                return parsed.model_dump_json()
            return json.dumps(parsed)
        tool_calls = getattr(message, "tool_calls", None) or []
        for tool_call in tool_calls:
            function = getattr(tool_call, "function", None)
            arguments = getattr(function, "arguments", None)
            if isinstance(arguments, str) and arguments.strip():
                return arguments
            if isinstance(arguments, dict):
                return json.dumps(arguments)
        return ""

    def _parse_pydantic_response(
        self,
        response: Any,
        response_model: type[StructuredModelT],
    ) -> StructuredModelT:
        """Validate a structured model response into a Pydantic object."""
        message = response.choices[0].message
        parsed = getattr(message, "parsed", None)
        if parsed is not None:
            try:
                return response_model.model_validate(parsed)
            except ValidationError as exc:
                raise ParsingError(f"LLM returned invalid structured payload: {exc}") from exc

        text = self._extract_response_text(response).strip()
        fence_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
        if fence_match:
            text = fence_match.group(1).strip()
        try:
            return response_model.model_validate_json(text)
        except ValidationError as exc:
            raise ParsingError(f"LLM returned invalid structured payload: {exc}") from exc


def _strict_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Normalize a Pydantic schema for OpenAI strict structured outputs."""
    normalized = deepcopy(schema)
    return _strict_json_schema_node(normalized)


def _strict_json_schema_node(node: Any) -> Any:
    """Recursively enforce strict object requirements on a JSON schema node."""
    if isinstance(node, list):
        return [_strict_json_schema_node(item) for item in node]
    if not isinstance(node, dict):
        return node

    for key in ("properties", "$defs", "definitions"):
        value = node.get(key)
        if isinstance(value, dict):
            node[key] = {k: _strict_json_schema_node(v) for k, v in value.items()}

    if "items" in node:
        node["items"] = _strict_json_schema_node(node["items"])

    for key in ("anyOf", "oneOf", "allOf", "prefixItems"):
        if key in node and isinstance(node[key], list):
            node[key] = [_strict_json_schema_node(item) for item in node[key]]

    if node.get("type") == "object":
        properties = node.get("properties")
        if isinstance(properties, dict):
            node["required"] = list(properties.keys())
        node.setdefault("additionalProperties", False)

    return node


def infer_runtime_preference(
    *,
    text_blobs: list[str | None] | None = None,
    supporting_files: Optional[list[str]] = None,
) -> str:
    """Infer the preferred implementation/runtime language for a skill."""
    scores = {"python": 0, "javascript": 0, "shell": 0}

    for path in supporting_files or []:
        suffix = Path(path).suffix.lower()
        if suffix == ".py":
            scores["python"] += 3
        elif suffix in _JS_SCRIPT_SUFFIXES:
            scores["javascript"] += 3
        elif suffix in {".sh", ".bash", ".zsh"}:
            scores["shell"] += 2

    text = "\n".join(part for part in (text_blobs or []) if part).lower()
    python_markers = (
        " in python",
        "python runner",
        "python script",
        "python cli",
        "python implementation",
        "argparse",
        "uv run",
        "pytest",
    )
    javascript_markers = (
        " in javascript",
        " in typescript",
        "node",
        "javascript runner",
        "typescript",
        "npm ",
        "pnpm ",
        "bun ",
        "ts-node",
    )
    shell_markers = (
        "shell script",
        "bash script",
        "zsh script",
        "#!/usr/bin/env bash",
        "#!/usr/bin/env sh",
    )
    for marker in python_markers:
        if marker in text:
            scores["python"] += 2
    for marker in javascript_markers:
        if marker in text:
            scores["javascript"] += 2
    for marker in shell_markers:
        if marker in text:
            scores["shell"] += 2

    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "unspecified"


def render_runtime_guidance(runtime_preference: str) -> str:
    """Render runtime-preservation instructions for prompts."""
    if runtime_preference == "python":
        return (
            "- Preserve the skill's implementation language as Python.\n"
            "- Prefer runnable support files under `scripts/*.py` and Python-oriented examples/tests.\n"
            "- Do not introduce JavaScript or TypeScript entrypoints unless the existing source or user request explicitly requires them.\n"
        )
    if runtime_preference == "javascript":
        return (
            "- Preserve the skill's implementation language as JavaScript or TypeScript.\n"
            "- Prefer runnable support files under `scripts/*.js` or `scripts/*.ts`.\n"
            "- Do not introduce Python entrypoints unless the existing source or user request explicitly requires them.\n"
        )
    if runtime_preference == "shell":
        return "- Preserve shell-based runnable support files where the skill is primarily shell-oriented.\n"
    return ""


# ── Legacy compatibility wrapper ──────────────────────────────────────


def generate_skill_content(
    name: str,
    description: str,
    source_context: Optional[str] = None,
    *,
    model: Optional[str] = None,
    supporting_files: Optional[list[str]] = None,
) -> Tuple[str, str]:
    """Compatibility wrapper for the new LLMClient."""
    client = LLMClient(model=model)
    return client.generate_skill_content(
        name,
        description,
        source_context,
        supporting_files=supporting_files,
    )


def revise_skill_content(
    name: str,
    current_skill_md: str,
    improvement_prompt: str,
    *,
    model: Optional[str] = None,
    supporting_files: Optional[list[str]] = None,
) -> Tuple[str, str]:
    """Compatibility wrapper for iterative skill improvement."""
    client = LLMClient(model=model)
    return client.revise_skill_content(
        name,
        current_skill_md,
        improvement_prompt,
        supporting_files=supporting_files,
    )


def generate_support_file_content(
    skill_name: str,
    current_skill_md: str,
    relative_path: str,
    *,
    niche_examples: str = "",
    model: Optional[str] = None,
    supporting_files: Optional[list[str]] = None,
) -> str:
    """Compatibility wrapper for support-file generation."""
    client = LLMClient(model=model)
    return client.generate_support_file_content(
        skill_name,
        current_skill_md,
        relative_path,
        niche_examples=niche_examples,
        supporting_files=supporting_files,
    )
