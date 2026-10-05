"""Notes whose Missed section was last written on a given day, with their missed points. Takes a `Collection`; no aqt."""

import re

from . import missed
from .textutil import strip_html

_DATE = re.compile(r"<b>\s*Missed\s*\(([^)]*)\)", re.I)


def missed_on(col, date: str) -> list:
    """[(deck name, [{"nid", "front", "reviews", "items": [(html, count)]}])], decks and notes sorted by name / most
    missed first. Notes whose review missed nothing are left out."""
    by_deck = {}
    for nid in col.find_notes(f'"Missed ({date})"'):
        note = col.get_note(nid)
        field = missed.pick_missed_field(note.keys())
        text = note[field] if field else ""
        m = _DATE.search(text)
        reviews, items = missed.parse_missed(text)
        if not m or m.group(1).strip() != date or not items:  # the search is loose: check the stamp itself
            continue
        card = note.cards()[0]
        deck = col.decks.name(card.odid or card.did)  # a filtered deck shows the card's home deck
        by_deck.setdefault(deck, []).append(
            {"nid": nid, "front": strip_html(note.fields[0]), "reviews": reviews, "items": items})
    for notes in by_deck.values():
        notes.sort(key=lambda n: -max(c for _, c in n["items"]))
    return sorted(by_deck.items())
