"""Runs against a real (temporary) Anki collection; skipped where Anki's Python packages aren't importable.

Run with Anki's own interpreter, e.g.
  ANKI_PY=~/Library/Application\\ Support/AnkiProgramFiles/.venv/bin/python3
  uvx --native-tls --python "$ANKI_PY" pytest -q -p no:cacheprovider tests/test_generate_col.py
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
APP = "/Applications/Anki.app/Contents/Resources/app_packages"
if os.path.isdir(APP):
    sys.path.append(APP)

Collection = pytest.importorskip("anki.collection").Collection

from addon import generate_col as gc, generate_ops as g  # noqa: E402


@pytest.fixture
def col(tmp_path):
    c = Collection(str(tmp_path / "c.anki2"))
    note = c.new_note(c.models.by_name("Basic"))
    note["Front"], note["Back"] = "What makes ATP?", "Mitochondria"
    note.tags = ["bio"]
    c.add_note(note, c.decks.id("Biology::Ch3"))
    yield c
    c.close()


def decks(c):
    return [d.name for d in c.decks.all_names_and_ids()]


def stage(c, changes):
    existing = {n["id"]: n for n in gc.read_deck(c, "Biology")}
    ops, rejected = g.plan_changes(changes, decks(c), existing, gc.staged(c))
    assert rejected == []
    return gc.apply_ops(c, ops)[1]


def test_stage_accept(col):
    orig = gc.read_deck(col, "Biology")[0]
    counts = stage(col, [
        {"add": {"deck": "Biology::Ch4", "type": "basic", "front": "Ribosomes?", "back": "Protein"}},
        {"add": {"deck": "Biology::Ch3", "type": "cloze", "text": "{{c1::Mitochondria}} make ATP"}},
        {"update": {"note_id": orig["id"], "fields": {"Back": "Mitochondria (cellular respiration)"}}},
    ])
    assert counts == {"added": 2, "updated": 1, "edited": 0, "removed": 0}
    s = gc.staged(col)
    assert [(x["deck"], x["of"]) for x in s] == [("Biology::Ch3", None), ("Biology::Ch3", orig["id"]),
                                                 ("Biology::Ch4", None)]
    assert "AI-GEN::Biology::Ch4" in decks(col) and "Biology::Ch4" not in decks(col)
    assert col.get_note(orig["id"])["Back"] == "Mitochondria"  # original untouched until Accept
    assert len(gc.read_deck(col, "Biology")) == 1  # staged copies aren't "existing" cards

    # a second update of the same note changes the staged copy, not a new one
    stage(col, [{"update": {"note_id": orig["id"], "fields": {"Back": "Mitochondria!"}}}])
    assert len(gc.staged(col)) == 3

    _, counts = gc.submit(col)
    assert counts == {"updated": 0, "added": 0, "moved": 0}  # nothing approved yet: Submit ports nothing
    assert gc.approve(col)[1] == 3
    _, counts = gc.submit(col)
    assert counts == {"updated": 1, "added": 2, "moved": 0}
    assert col.get_note(orig["id"])["Back"] == "Mitochondria!" and col.get_note(orig["id"]).tags == ["bio"]
    assert not any(n.startswith("AI-GEN") for n in decks(col)) and "Biology::Ch4" in decks(col)
    cards = gc.read_deck(col, "Biology")
    assert len(cards) == 3 and {c["deck"] for c in cards} == {"Biology::Ch3", "Biology::Ch4"}
    assert all(not {gc.TAG, gc.OK} & set(col.get_note(c["id"]).tags) for c in cards)


def test_edit_remove_discard_undo(col):
    stage(col, [{"add": {"deck": "Biology", "front": "a", "back": "b"}},
                {"add": {"deck": "Biology", "front": "c", "back": "d"}}])
    stage(col, [{"edit": {"staged": 1, "fields": {"Back": "B"}}}, {"remove": 2}])
    s = gc.staged(col)
    assert [x["fields"]["Back"] for x in s] == ["B"]
    _, n = gc.discard(col)
    assert n == 1 and gc.staged(col) == [] and col.decks.id_for_name("AI-GEN") is None
    assert col.note_count() == 1
    col.undo()  # one undo step brings the whole staged deck back
    assert len(gc.staged(col)) == 1


def test_approve_some_keep_generating_then_submit(col):
    stage(col, [{"add": {"deck": "Physics::Waves", "front": "c?", "back": "speed of light"}},
                {"add": {"deck": "Biology", "front": "a", "back": "b"}}])
    physics = [s["id"] for s in gc.staged(col) if s["deck"] == "Physics::Waves"]
    assert gc.approve(col, physics)[1] == 1
    stage(col, [{"add": {"deck": "Chem", "front": "x", "back": "y"}}])  # generate more after approving
    assert {s["deck"]: s["ok"] for s in gc.staged(col)} == {"Biology": False, "Chem": False, "Physics::Waves": True}
    _, counts = gc.submit(col)
    assert counts == {"updated": 0, "added": 1, "moved": 0}
    assert "Physics::Waves" in decks(col) and "AI-GEN::Physics" not in decks(col)  # emptied parent removed too
    assert sorted(s["deck"] for s in gc.staged(col)) == ["Biology", "Chem"]  # unapproved stay staged
    _, n = gc.discard(col, [gc.staged(col)[0]["id"]])
    assert n == 1 and [s["deck"] for s in gc.staged(col)] == ["Chem"]


def test_ai_edit_unapproves(col):
    stage(col, [{"add": {"deck": "Biology", "front": "a", "back": "b"}}])
    gc.approve(col)
    stage(col, [{"edit": {"staged": 1, "fields": {"Back": "B"}}}])
    assert gc.staged(col)[0]["ok"] is False
    gc.approve(col)
    gc.approve(col, ok=False)
    assert gc.staged(col)[0]["ok"] is False


def test_big_batch_is_one_undo_step(col):
    """Anki keeps ~30 undo steps; a per-card op loop overflowed it ("target undo op not found")."""
    stage(col, [{"add": {"deck": f"Big::D{i % 3}", "front": f"q{i}", "back": "a"}} for i in range(60)])
    gc.approve(col)
    _, counts = gc.submit(col)
    assert counts == {"updated": 0, "added": 60, "moved": 0} and gc.staged(col) == []
    col.undo()  # the whole Submit is one step: everything is back in AI-GEN, still approved
    assert len(gc.staged(col)) == 60 and all(s["ok"] for s in gc.staged(col))


def test_submit_writes_only_fields_changed_since_staging(col):
    """A review between staging and Submit appends a Missed section to Back: an update of Front must keep it."""
    orig = gc.read_deck(col, "Biology")[0]
    stage(col, [{"update": {"note_id": orig["id"], "fields": {"Front": "What makes ATP? (organelle)"}}}])
    note = col.get_note(orig["id"])
    note["Back"] += "<hr><b>Missed (D)</b>"
    col.update_note(note)
    gc.approve(col)
    _, counts = gc.submit(col)
    note = col.get_note(orig["id"])
    assert counts["updated"] == 1 and note["Front"] == "What makes ATP? (organelle)"
    assert note["Back"] == "Mitochondria<hr><b>Missed (D)</b>" and not any(t.startswith(gc.BASE) for t in note.tags)


def test_move_keeps_scheduling(col):
    """An update with a deck moves the original on Submit: same note and card, review history kept,
    even when the card sits in a filtered deck."""
    orig = gc.read_deck(col, "Biology")[0]
    cid = col.get_note(orig["id"]).card_ids()[0]
    card = col.get_card(cid)
    card.type, card.queue, card.ivl, card.due, card.factor = 2, 2, 30, col.sched.today + 5, 2600
    col.update_card(card)
    fid = col.decks.new_filtered("Cram")
    f = col.decks.get(fid)
    f["terms"] = [["deck:Biology", 100, 0]]
    col.decks.save(f)
    col.sched.rebuild_filtered_deck(fid)
    assert col.get_card(cid).odid

    stage(col, [{"update": {"note_id": orig["id"], "deck": "Biology::Ch4::Energy"}}])
    s = gc.staged(col)
    assert [(x["deck"], x["from"]) for x in s] == [("Biology::Ch4::Energy", "Biology::Ch3")]
    assert "AI-GEN::Biology::Ch4::Energy" in decks(col) and "Biology::Ch4" not in decks(col)
    assert '"kind": "update of note %d, moves it from Biology::Ch3"' % orig["id"] in g.cards_context(decks(col), staged=s)
    gc.approve(col)
    _, counts = gc.submit(col)
    assert counts == {"updated": 1, "added": 0, "moved": 1}
    card = col.get_card(cid)
    assert col.decks.name(card.did) == "Biology::Ch4::Energy" and not card.odid
    assert (card.ivl, card.due, card.factor, card.type) == (30, col.sched.today + 5, 2600, 2)
    note = col.get_note(orig["id"])
    assert note["Back"] == "Mitochondria" and note.tags == ["bio"] and col.note_count() == 1
    assert not any(n.startswith("AI-GEN") for n in decks(col))
    col.undo()
    assert col.decks.name(col.get_card(cid).odid) == "Biology::Ch3" and len(gc.staged(col)) == 1


def test_move_with_edit_and_back(col):
    orig = gc.read_deck(col, "Biology")[0]
    stage(col, [{"update": {"note_id": orig["id"], "fields": {"Back": "Mito"}}}])
    assert gc.staged(col)[0]["from"] is None
    stage(col, [{"edit": {"staged": 1, "deck": "Chem"}}])  # a staged update copy moved by edit
    assert [(x["deck"], x["from"]) for x in gc.staged(col)] == [("Chem", "Biology::Ch3")]
    stage(col, [{"edit": {"staged": 1, "deck": "Biology::Ch3"}}])  # moved back home: no move left
    assert [(x["deck"], x["from"]) for x in gc.staged(col)] == [("Biology::Ch3", None)]
    stage(col, [{"add": {"deck": "Biology", "front": "a", "back": "b"}}])
    new = next(x for x in gc.staged(col) if not x["of"])
    stage(col, [{"edit": {"staged": gc.staged(col).index(new) + 1, "deck": "Physics"}}])  # a new card just goes elsewhere
    assert {x["deck"]: x["from"] for x in gc.staged(col)} == {"Biology::Ch3": None, "Physics": None}
    gc.approve(col)
    _, counts = gc.submit(col)
    assert counts == {"updated": 1, "added": 1, "moved": 0}
    assert {c["deck"] for c in gc.read_deck(col, "Biology")} == {"Biology::Ch3"} and gc.read_deck(col, "Physics")
