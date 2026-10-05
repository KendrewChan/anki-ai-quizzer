"""Text helpers shared by every prompt module: the style guide, HTML to text, the AI's JSON replies, safe rich text.
No Anki imports."""

import html
import json
import re
from pathlib import Path

# How the AI formats text (bold, HTML fields, LaTeX); appended to every system prompt.
STYLE_GUIDE = Path(__file__).with_name("style.md").read_text(encoding="utf-8").strip()


def strip_html(text: str) -> str:
    """Rendered card HTML -> plain text."""
    text = re.sub(r"(?is)<(style|script)\b.*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|h\d)>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t ]+", " ", text)
    return re.sub(r"\s*\n\s*", "\n", text).strip()


def safe_html(text: str) -> str:
    """A note field's HTML for display in an add-on page: formatting and colours kept, scripts and handlers removed."""
    text = re.sub(r"(?is)<(script|style|iframe|object|embed)\b.*?</\1\s*>", "", text)
    text = re.sub(r"(?i)</?(script|style|iframe|object|embed)\b[^>]*>", "", text)
    text = re.sub(r"""(?i)\s+on\w+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""", "", text)
    return re.sub(r"""(?i)(href|src)(\s*=\s*["']?)\s*javascript:""", r"\1\2#", text)


def parse_json_reply(text: str) -> dict:
    """Extract the first JSON object from a model reply (tolerates code fences / stray prose)."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end < start:
        raise ValueError(f"no JSON object in reply: {text[:200]!r}")
    raw = text[start:end + 1]
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        # LaTeX written with single backslashes (\( \sqrt …) is invalid JSON: double the stray ones and retry.
        obj = json.loads(re.sub(r"\\(.)", lambda m: m.group(0) if m.group(1) in '"\\/bfnrtu' else "\\\\" + m.group(1),
                                raw, flags=re.S))
    if not isinstance(obj, dict):
        raise ValueError("reply JSON is not an object")
    return _fix_latex(obj)


_LATEX_CTRL = {"\b": "\\b", "\f": "\\f", "\t": "\\t", "\r": "\\r"}


def _fix_latex(value):
    """Single-backslash \\frac, \\times, \\beta, \\right parse as control characters: turn them back into LaTeX."""
    if isinstance(value, str):
        return re.sub(r"[\b\f\t\r](?=[A-Za-z])", lambda m: _LATEX_CTRL[m.group()], value)
    if isinstance(value, list):
        return [_fix_latex(v) for v in value]
    if isinstance(value, dict):
        return {k: _fix_latex(v) for k, v in value.items()}
    return value


def rich(text: str) -> str:
    """AI short text -> safe HTML: escaped, **bold** -> <b>. LaTeX \\( \\) passes through for Anki's MathJax."""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html.escape(text))
