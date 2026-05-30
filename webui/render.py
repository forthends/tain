"""
Content renderer — converts knowledge files to HTML for display.

No external dependencies. Handles the Markdown subset used by agents.
"""
import re
import json as _json
from functools import lru_cache
from html import escape


def _escape_html(text: str) -> str:
    return escape(text)


@lru_cache(maxsize=64)
def render_markdown(text: str) -> str:
    """Render a Markdown string to HTML.

    Handles: headings, bold, italic, code blocks, inline code, links,
    images, lists (ordered/unordered), horizontal rules, blockquotes,
    tables, and paragraphs.
    """
    lines = text.split("\n")
    html: list[str] = []
    in_code_block = False
    in_table = False
    in_blockquote = False
    code_lang = ""
    code_lines: list[str] = []
    table_rows: list[str] = []
    list_buffer: list[str] = []  # accumulate adjacent list items
    list_type: str | None = None  # 'ul' or 'ol'

    def flush_list() -> None:
        nonlocal list_type
        if list_buffer:
            items = "".join(f"<li>{item}</li>" for item in list_buffer)
            tag = list_type or "ul"
            html.append(f"<{tag}>{items}</{tag}>")
            list_buffer.clear()
            list_type = None

    def flush_table() -> None:
        nonlocal in_table
        if table_rows:
            thead = ""
            tbody = ""
            # Check if row 2 is a separator line (---|---)
            if len(table_rows) > 2 and all(
                re.match(r"^[\s\-:|]+$", c.strip()) for c in table_rows[1].split("|")[1:-1]
            ):
                header_cells = [c.strip() for c in table_rows[0].split("|")[1:-1]]
                thead = "<thead><tr>" + "".join(
                    f"<th>{_inline_render(cell)}</th>" for cell in header_cells
                ) + "</tr></thead>"
                body_start = 2
            else:
                body_start = 0
            if len(table_rows) > body_start:
                body_rows = []
                for row in table_rows[body_start:]:
                    cells = [c.strip() for c in row.split("|")[1:-1]]
                    body_rows.append("<tr>" + "".join(
                        f"<td>{_inline_render(cell)}</td>" for cell in cells
                    ) + "</tr>")
                tbody = "<tbody>" + "".join(body_rows) + "</tbody>"
            html.append(f'<table class="md-table">{thead}{tbody}</table>')
            table_rows.clear()
            in_table = False

    def flush_code_block() -> None:
        nonlocal in_code_block
        lang_attr = f' class="language-{code_lang}"' if code_lang else ""
        code = escape("\n".join(code_lines))
        html.append(f"<pre><code{lang_attr}>{code}</code></pre>")
        code_lines.clear()
        in_code_block = False

    def flush_blockquote() -> None:
        pass  # blockquotes rendered inline

    def _inline_render(text: str) -> str:
        """Render inline Markdown within a single line."""
        t = escape(text)
        # Images (must be before links)
        t = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r'<img src="\2" alt="\1">', t)
        # Links
        t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2" class="text-blue-500 hover:underline">\1</a>', t)
        # Bold + Italic
        t = re.sub(r"\*\*\*(.+?)\*\*\*", r"<strong><em>\1</em></strong>", t)
        # Bold
        t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
        # Italic
        t = re.sub(r"\*(.+?)\*", r"<em>\1</em>", t)
        # Inline code
        t = re.sub(r"`([^`]+)`", r'<code class="inline-code">\1</code>', t)
        # Strikethrough
        t = re.sub(r"~~(.+?)~~", r"<del>\1</del>", t)
        return t

    i = 0
    while i < len(lines):
        line = lines[i]

        # ── Fenced code block ──
        if line.strip().startswith("```"):
            if not in_code_block:
                flush_list()
                flush_table()
                in_code_block = True
                code_lang = line.strip()[3:].strip()
                code_lines = []
            else:
                flush_code_block()
            i += 1
            continue

        if in_code_block:
            code_lines.append(line)
            i += 1
            continue

        # ── Table ──
        if line.strip().startswith("|") and line.strip().endswith("|"):
            flush_list()
            flush_blockquote()
            if not in_table:
                in_table = True
                table_rows = []
            table_rows.append(line.strip())
            # Check if next line is also table
            if i + 1 < len(lines) and lines[i + 1].strip().startswith("|"):
                i += 1
                continue
            else:
                flush_table()
                i += 1
                continue

        # ── Horizontal rule ──
        if re.match(r"^[\s]*[-*_]{3,}[\s]*$", line):
            flush_list()
            html.append("<hr>")
            i += 1
            continue

        # ── Headings ──
        h_match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if h_match:
            flush_list()
            level = len(h_match.group(1))
            content = _inline_render(h_match.group(2))
            html.append(f"<h{level} class='md-heading md-h{level}'>{content}</h{level}>")
            i += 1
            continue

        # ── Unordered list ──
        ul_match = re.match(r"^(\s*)[-*+]\s+(.+)$", line)
        if ul_match:
            if list_type != "ul":
                flush_list()
                list_type = "ul"
            list_buffer.append(_inline_render(ul_match.group(2)))
            i += 1
            continue

        # ── Ordered list ──
        ol_match = re.match(r"^(\s*)\d+[.)]\s+(.+)$", line)
        if ol_match:
            if list_type != "ol":
                flush_list()
                list_type = "ol"
            list_buffer.append(_inline_render(ol_match.group(2)))
            i += 1
            continue

        # ── Blockquote ──
        bq_match = re.match(r"^>\s?(.*)$", line)
        if bq_match:
            flush_list()
            flush_table()
            content = _inline_render(bq_match.group(1))
            html.append(f'<blockquote class="md-blockquote">{content}</blockquote>')
            i += 1
            continue

        # ── Empty line → paragraph break ──
        if not line.strip():
            flush_list()
            flush_table()
            html.append("")
            i += 1
            continue

        # ── Regular paragraph ──
        flush_list()
        flush_table()
        html.append(f"<p>{_inline_render(line)}</p>")
        i += 1

    # Clean up any remaining buffered content
    flush_list()
    flush_table()
    if in_code_block:
        flush_code_block()

    return "\n".join(html)


def render_json(text: str) -> str:
    """Render JSON with syntax highlighting."""
    try:
        parsed = _json.loads(text)
        formatted = _json.dumps(parsed, ensure_ascii=False, indent=2)
    except _json.JSONDecodeError:
        formatted = text
    escaped = escape(formatted)
    # Simple syntax highlighting for JSON
    escaped = re.sub(
        r'("(?:[^"\\]|\\.)*")\s*:',
        r'<span class="json-key">\1</span>:',
        escaped,
    )
    escaped = re.sub(
        r':\s*("(?:[^"\\]|\\.)*")',
        r': <span class="json-string">\1</span>',
        escaped,
    )
    escaped = re.sub(
        r":\s*(\d+\.?\d*)",
        r': <span class="json-number">\1</span>',
        escaped,
    )
    escaped = re.sub(
        r":\s*(true|false|null)",
        r': <span class="json-bool">\1</span>',
        escaped,
    )
    return f"<pre><code>{escaped}</code></pre>"


def render_text(text: str) -> str:
    """Render plain text."""
    return f"<pre class='text-sm'>{escape(text)}</pre>"


def render_content(text: str, fmt: str) -> str:
    """Render content based on format type. Returns HTML string."""
    if fmt == "markdown":
        return render_markdown(text)
    elif fmt == "json":
        return render_json(text)
    else:
        return render_text(text)
