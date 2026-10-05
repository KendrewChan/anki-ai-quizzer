"""Runs against a real (temporary) Anki collection; skipped where Anki's Python packages aren't importable
(see test_generate_col.py for how to run)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
APP = "/Applications/Anki.app/Contents/Resources/app_packages"
if os.path.isdir(APP):
    sys.path.append(APP)

Collection = pytest.importorskip("anki.collection").Collection

from addon import missed, missed_today  # noqa: E402


@pytest.fixture
def col(tmp_path):
    c = Collection(str(tmp_path / "c.anki2"))
    yield c
    c.close()


def add(c, deck, front, back):
    note = c.new_note(c.models.by_name("Basic"))
    note["Front"], note["Back"] = front, back
    c.add_note(note, c.decks.id(deck))
    return note


def test_lists_only_todays_notes_with_misses(col):
    add(col, "Bio::Ch3", "ATP?", missed.replace_missed("x", ["makes **ATP**"], "2026-10-05"))
    add(col, "Bio::Ch3", "old", missed.replace_missed("x", ["old point"], "2026-10-04"))
    add(col, "Chem", "clean", missed.replace_missed("x", [], "2026-10-05"))  # "nothing": left out
    add(col, "Chem", "never reviewed", "x")
    out = missed_today.missed_on(col, "2026-10-05")
    assert [d for d, _ in out] == ["Bio::Ch3"]
    note = out[0][1][0]
    assert note["front"] == "ATP?" and note["reviews"] == 1 and note["items"] == [("makes <b>ATP</b>", 1)]


def test_most_missed_note_first(col):
    once = missed.replace_missed("x", ["a"], "2026-10-05")
    thrice = once
    for _ in range(2):
        thrice = missed.replace_missed(thrice, ["a"], "2026-10-05")
    add(col, "D", "once", once)
    add(col, "D", "thrice", thrice)
    assert [n["front"] for n in missed_today.missed_on(col, "2026-10-05")[0][1]] == ["thrice", "once"]
