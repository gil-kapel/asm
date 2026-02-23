"""LLM-backed generation for skill content. Uses LiteLLM when the [llm] extra is installed."""

from __future__ import annotations

import os

# LiteLLM is optional; import at call time so ASM runs without [llm] extra.


def _ensure_litellm() -> None:
    try:
        import litellm  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            "LLM support requires the [llm] extra. Install with: uv pip install asm[llm]"
        ) from e


def _get_model() -> str:
    return os.environ.get("ASM_LLM_MODEL", "openai/gpt-4o-mini").strip()


def generate_skill_content(
    name: str,
    description: str,
    source_context: str | None = None,
    *,
    model: str | None = None,
) -> tuple[str, str]:
    """Generate SKILL.md description (frontmatter) and body markdown using an LLM.

    Uses LiteLLM; provider API keys must be set (e.g. OPENAI_API_KEY, ANTHROPIC_API_KEY).
    Returns (description_for_frontmatter, body_markdown).
    """
    _ensure_litellm()
    import litellm

    model = (model or os.environ.get("ASM_LLM_MODEL") or "openai/gpt-4o-mini").strip()

    system = """You are an expert at writing agent skills in SKILL.md format.
- If source context is provided (e.g. README, docs), you MUST use it to write specific, detailed Instructions and Usage. Do not output a generic placeholder; distill the actual content.
- Output only valid markdown. The description must be one line, third person, and include both what the skill does and when an agent should use it (trigger terms).
- The body must have: ## Instructions (concrete steps based on the source), ## Usage (when to use), and optionally ## Examples. No YAML frontmatter in the body.
- You MUST include the exact delimiter ---BODY--- on its own line between part 1 and part 2."""

    user_parts = [
        f"Skill name: {name}",
        f"User description: {description}",
    ]
    if source_context:
        user_parts.append(
            "Source context below — use it to write detailed, specific instructions. Do not ignore it.\n\n"
            + source_context[:12000]
        )
    user_parts.append(
        "Respond with exactly two parts separated by '---BODY---' on its own line. "
        "Part 1: one line for the frontmatter description. Part 2: the full SKILL.md body (## Instructions, ## Usage, ## Examples as appropriate) based on the source."
    )
    user_msg = "\n\n".join(user_parts)

    try:
        response = litellm.completion(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=4096,
        )
    except Exception as e:
        raise RuntimeError(
            f"LLM call failed: {e}. Check API key (e.g. OPENAI_API_KEY) and ASM_LLM_MODEL."
        ) from e

    content = (response.choices[0].message.content or "").strip()
    if not content:
        body = f"# {name.replace('-', ' ').title()}\n\n## Instructions\n\n{description}\n\n## Usage\n\nUse when the user or task matches the description above.\n"
        return description.strip(), body

    if "---BODY---" in content:
        part1, _, part2 = content.partition("---BODY---")
        first_line = part1.strip().split("\n")[0].strip().strip('"')
        if first_line.lower().startswith("description:"):
            first_line = first_line[11:].strip()
        desc = first_line or description.strip()
        body = part2.strip()
        return desc, body

    # Model omitted delimiter but returned content: use full response as body
    lines = content.split("\n")
    first_line = lines[0].strip().strip("#\"'") if lines else ""
    if first_line.lower().startswith("description:"):
        first_line = first_line[11:].strip()
    if len(first_line) <= 120 and not first_line.startswith("#"):
        desc = first_line or description.strip()
        body = content
    else:
        desc = description.strip()
        body = content
    return desc, body
