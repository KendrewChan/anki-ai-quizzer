"""The Missed section kept at the end of a note's back field: each point with how many graded reviews missed it.
No Anki imports."""

import html
import re

from .textutil import rich


# A Missed section as written by this add-on (tolerant of editor reformatting).
MISSED_SECTION = re.compile(
    r"\s*<hr[^>]*>\s*<b>\s*Missed\s*\([^)]*\)\s*</b>(?:\s*<i>[^<]*reviews?\s*</i>)?\s*(?::\s*nothing|<ul>.*?</ul>)?", re.I | re.S
)


MAX_MISSED = 12  # points kept in a note's Missed section; the least-missed (then oldest) are dropped
_LI = re.compile(r"<li>(.*?)</li>", re.I | re.S)
_COUNT = re.compile(r"^\s*<b[^>]*>\s*\[(\d+)\]\s*</b>\s*", re.I)  # the count, as written in front of a point
_OLD_COUNT = re.compile(r"\s*<i>\s*×\s*(\d+)\s*</i>\s*$", re.I)  # earlier versions put "×N" after it
RED_FROM = 3  # a point missed this many times or more is marked red
_REVIEWS = re.compile(r"<i>\s*(\d+)\s+reviews?\s*</i>", re.I)


def _count_html(n: int) -> str:
    return f'<b style="color:#d33">[{n}]</b>' if n >= RED_FROM else f"<b>[{n}]</b>"


def missed_html(items: list, date: str, reviews: int = 1) -> str:
    """items: [(html, times missed)]. The header counts the graded reviews, so "[3]" among "5 reviews" is a frequency."""
    head = f"<hr><b>Missed ({date})</b> <i>{reviews} review{'s' if reviews != 1 else ''}</i>"
    if not items:
        return f"{head}: nothing"
    return head + "<ul>" + "".join(f"<li>{_count_html(n)} {h}</li>" for h, n in items) + "</ul>"


def parse_missed(field_html: str) -> tuple:
    """(reviews, [(html, count)]) from the note's Missed section; (0, []) if it has none. A section written before
    counting existed counts as one review with each point missed once."""
    m = MISSED_SECTION.search(field_html)
    if not m:
        return 0, []
    r = _REVIEWS.search(m.group(0))
    items = []
    for li in _LI.findall(m.group(0)):
        c = _COUNT.search(li) or _OLD_COUNT.search(li)
        items.append((_COUNT.sub("", _OLD_COUNT.sub("", li)).strip(), int(c.group(1)) if c else 1))
    return (int(r.group(1)) if r else 1), items


def _words(text: str) -> set:
    return set(re.findall(r"\w+", html.unescape(re.sub(r"<[^>]+>", " ", text)).lower()))


def _same_point(a: str, b: str) -> bool:
    """The same missed point worded alike: equal words, one inside the other, or mostly shared words."""
    x, y = _words(a), _words(b)
    if not x or not y:
        return False
    return x <= y or y <= x or len(x & y) / len(x | y) >= 0.6


def merge_missed(items: list, bullets: list) -> list:
    """Add one miss for each of this review's bullets: to the point already listed, else as a new one."""
    items, seen = list(items), set()
    for b in bullets:
        k = next((i for i, (h, _) in enumerate(items) if i not in seen and _same_point(h, b)), None)
        if k is None:
            items.append((rich(b), 1))
            seen.add(len(items) - 1)
        else:
            items[k] = (items[k][0], items[k][1] + 1)
            seen.add(k)
    items = sorted(items, key=lambda it: -it[1])  # stable: ties keep the older point first
    return items[:MAX_MISSED]


def replace_missed(field_html: str, bullets: list, date: str) -> str:
    """Keep exactly one Missed section: each point with how many reviews missed it, out of all graded reviews."""
    reviews, items = parse_missed(field_html)
    return (MISSED_SECTION.sub("", field_html).rstrip()
            + missed_html(merge_missed(items, bullets), date, reviews + 1))


def pick_missed_field(field_names: list):
    """Back -> Back Extra -> last field. None if the note has no fields."""
    for name in ("Back", "Back Extra"):
        if name in field_names:
            return name
    return field_names[-1] if field_names else None
