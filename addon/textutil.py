"""Text helpers shared by every prompt module: the style guide, HTML to text, the AI's JSON replies, safe rich text.
No Anki imports."""

import html
import json
import re
from html.parser import HTMLParser
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


_SAFE_TAGS = set("a abbr b big blockquote br caption center code col colgroup dd del div dl dt em font h1 h2 h3 h4 h5 h6 "
                 "hr i img ins kbd li mark ol p pre q rp rt ruby s small span strike strong sub sup table tbody td tfoot "
                 "th thead tr tt u ul".split())
_VOID_TAGS = {"br", "col", "hr", "img"}
_DROP_WITH_CONTENT = {"script", "style", "iframe", "object", "embed", "template", "noscript", "textarea", "title"}
_SAFE_ATTRS = {"style", "class", "align", "valign", "colspan", "rowspan", "width", "height", "alt", "title", "color",
               "face", "size", "dir", "lang", "href", "src"}


def _safe_url(tag: str, value: str) -> bool:
    """Web links and relative paths (Anki media); data: only for images. Entities and whitespace can't hide a scheme."""
    url = re.sub(r"[\x00-\x20]", "", html.unescape(value)).lower()
    scheme = re.match(r"([a-z][a-z0-9+.-]*):", url)
    if not scheme:
        return True
    return scheme.group(1) in ("http", "https", "mailto") or (tag == "img" and url.startswith("data:image/"))


class _Sanitizer(HTMLParser):
    """Rebuilds HTML from an allowlist: known formatting tags and attributes only; everything else is dropped (its
    text kept, except inside script-like tags)."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in _DROP_WITH_CONTENT:
            self.skip += tag not in _VOID_TAGS
            return
        if self.skip or tag not in _SAFE_TAGS:
            return
        kept = []
        for name, value in attrs:
            value = value or ""
            if name not in _SAFE_ATTRS:
                continue
            if name in ("href", "src") and not _safe_url(tag, value):
                continue
            if name == "style" and re.search(r"expression|javascript|url\s*\(", html.unescape(value), re.I):
                continue
            kept.append(f' {name}="{html.escape(html.unescape(value))}"')
        self.out.append(f"<{tag}{''.join(kept)}>")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag in _DROP_WITH_CONTENT and tag not in _VOID_TAGS:
            self.skip -= 1

    def handle_endtag(self, tag):
        if tag in _DROP_WITH_CONTENT:
            self.skip = max(0, self.skip - 1)
        elif not self.skip and tag in _SAFE_TAGS and tag not in _VOID_TAGS:
            self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(html.escape(data, quote=False))

    def handle_entityref(self, name):
        if not self.skip:
            self.out.append(f"&{name};")

    def handle_charref(self, name):
        if not self.skip:
            self.out.append(f"&#{name};")


def safe_html(text: str) -> str:
    """A note field's (or the AI's) HTML for display in an add-on page: formatting and colours kept, anything that
    could run script removed."""
    parser = _Sanitizer()
    parser.feed(text)
    parser.close()
    return "".join(parser.out)


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
        obj = json.loads(re.sub(r"\\(u[0-9a-fA-F]{4}|.)",
                                lambda m: m.group(0) if len(m.group(1)) > 1 or m.group(1) in '"\\/bfnrt' else "\\\\" + m.group(1),
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
