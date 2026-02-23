"""LLM-backed generation for skill content.

Uses LiteLLM when the [llm] extra is installed.
Provides a robust client with centralized configuration and error handling.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_MODEL = "openai/gpt-4o-mini"
DEFAULT_MAX_TOKENS = 4096
BODY_DELIMITER = "---BODY---"


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
                "LLM support requires the [llm] extra. Install with: uv pip install asm[llm]"
            ) from e

    def completion(
        self,
        messages: List[dict[str, str]],
        max_tokens: int = DEFAULT_MAX_TOKENS,
        num_retries: int = 2,
        **kwargs: Any,
    ) -> str:
        """Execute a chat completion with error handling and logging."""
        import litellm

        try:
            logger.debug("Executing LLM completion with model: %s", self.model)
            response = litellm.completion(
                model=self.model,
                messages=messages,
                max_tokens=max_tokens,
                num_retries=num_retries,
                **kwargs,
            )
            content = response.choices[0].message.content or ""
            return content.strip()
        except Exception as e:
            logger.error("LLM completion failed: %s", e)
            raise ProviderError(f"LLM provider error: {e}") from e

    def generate_skill_content(
        self,
        name: str,
        description: str,
        source_context: Optional[str] = None,
    ) -> Tuple[str, str]:
        """Generate SKILL.md content using structured prompts and robust parsing."""
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(name, description, source_context)

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

    def _build_system_prompt(self) -> str:
        return (
            "You are an expert at writing agent skills in SKILL.md format.\n"
            "- If source context is provided, you MUST distill it into specific Instructions and Usage.\n"
            "- Output only valid markdown.\n"
            "- The description must be one line, third person, summarizing what the skill does and its triggers.\n"
            "- The body must include ## Instructions, ## Usage, and optionally ## Examples.\n"
            f"- You MUST separate the description and the body with exactly '{BODY_DELIMITER}' on its own line."
        )

    def _build_user_prompt(
        self, name: str, description: str, source_context: Optional[str]
    ) -> str:
        parts = [
            f"Skill name: {name}",
            f"Initial description: {description}",
        ]
        if source_context:
            # Truncate context to stay within common limits while leaving room for the response
            parts.append(f"Source context:\n\n{source_context[:15000]}")

        parts.append(
            f"Respond with:\n1. A one-line description\n2. {BODY_DELIMITER}\n3. The full markdown body"
        )
        return "\n\n".join(parts)

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
        text = re.sub(r"^(?i)(description|part\s*1):", "", text).strip()
        text = text.lstrip("#").strip()
        text = text.strip("\"' ")
        return text.split("\n")[0].strip()

    def _fallback_body(self, name: str, description: str) -> str:
        title = name.replace("-", " ").title()
        return (
            f"# {title}\n\n"
            f"## Instructions\n\n{description}\n\n"
            "## Usage\n\nUse when the task matches the description above.\n"
        )


# ── Legacy compatibility wrapper ──────────────────────────────────────


def generate_skill_content(
    name: str,
    description: str,
    source_context: Optional[str] = None,
    *,
    model: Optional[str] = None,
) -> Tuple[str, str]:
    """Compatibility wrapper for the new LLMClient."""
    client = LLMClient(model=model)
    return client.generate_skill_content(name, description, source_context)
