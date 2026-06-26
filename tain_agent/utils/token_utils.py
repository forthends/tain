"""
Token-aware text truncation utilities.

Provides token estimation and smart truncation that preserves
head and tail content while inserting a clear truncation marker.
"""


def estimate_tokens(text: str, model: str = "cl100k_base") -> int:
    """Estimate token count for a string.

    Tries tiktoken with the given model encoding, falls back to
    character-based estimate (~2.5 chars per token).

    Args:
        text: Text to estimate token count for.
        model: Tiktoken encoding name (default "cl100k_base").

    Returns:
        Estimated token count (minimum 1).
    """
    try:
        import tiktoken
        enc = tiktoken.get_encoding(model)
        return max(1, len(enc.encode(text)))
    except (ImportError, Exception):
        return max(1, len(text) * 2 // 5)


def truncate_text_by_tokens(text: str, max_tokens: int = 32000,
                            head_ratio: float = 0.5) -> str:
    """Truncate text to a token budget, preserving head and tail.

    Keeps `head_ratio` of the budget for the start of the text and
    the remainder for the end, with a truncation marker in between.

    Args:
        text: The full text to truncate.
        max_tokens: Maximum token budget.
        head_ratio: Fraction of budget for head content (0.0–1.0).
                    Default 0.5 splits evenly between head and tail.

    Returns:
        Text with truncation marker if truncation occurred,
        otherwise the original text.
    """
    if estimate_tokens(text) <= max_tokens:
        return text

    head_ratio = max(0.1, min(0.9, head_ratio))
    char_budget = max_tokens * 2
    head_chars = int(char_budget * head_ratio)
    tail_chars = int(char_budget * (1.0 - head_ratio))

    head = text[:head_chars]
    tail = text[-tail_chars:] if tail_chars > 0 else ""

    # Find natural break points
    if head_chars < len(text):
        for sep in ('\n\n', '\n', '. ', '。'):
            idx = head.rfind(sep)
            if idx > head_chars * 0.6:
                head = text[:idx + len(sep.rstrip())]
                break

    if tail_chars > 0 and tail_chars < len(text):
        for sep in ('\n\n', '\n', '. ', '。'):
            idx = text.find(sep, len(text) - tail_chars)
            if idx != -1:
                tail = text[idx:].lstrip()
                break

    original_tokens = estimate_tokens(text)
    marker = (
        f"\n\n... [Content truncated: ~{original_tokens} tokens "
        f"→ {max_tokens} token limit] ...\n\n"
    )

    return head + marker + tail


def truncate_lines(text: str, max_lines: int = 5000) -> str:
    """Truncate text to a maximum number of lines.

    Preserves the beginning and end of the output with a
    truncation marker in between.

    Args:
        text: The full text.
        max_lines: Maximum lines to keep.

    Returns:
        Truncated text with a marker if truncation occurred.
    """
    lines = text.split("\n")
    if len(lines) <= max_lines:
        return text

    head = lines[:max_lines * 3 // 4]
    tail = lines[-max_lines // 4:]
    return (
        "\n".join(head)
        + f"\n\n... [{len(lines) - max_lines} lines truncated] ...\n\n"
        + "\n".join(tail)
    )
