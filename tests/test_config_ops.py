import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from addon import config_ops, grading  # noqa: E402

BASE = {"claude_path": "/bin/claude", "models": {"claude": "sonnet", "codex": ""}, "missed_append": True,
        "ask_timeout_s": 30, "grade_timeout_s": 60, "custom": []}


def apply(changes, cfg=None, history=None, executable=True, decks=None):
    history = [] if history is None else history
    new, log, auth = config_ops.apply_changes(dict(cfg or BASE), changes, history, lambda p: executable, decks)
    return new, log, auth, history


def test_set_model_and_timeout_logged():
    new, log, _, hist = apply([{"set": {"model": "opus", "grade_timeout_s": "90"}}])
    assert new["models"]["claude"] == "opus" and new["grade_timeout_s"] == 90
    assert sorted(log) == ["✓ claude model: sonnet → opus", "✓ grade_timeout_s: 60 → 90"]
    assert hist == [BASE]


@pytest.mark.parametrize("change,msg", [
    ({"set": {"model": "gpt-4"}}, "unknown model"),
    ({"set": {"ask_timeout_s": 2}}, "between 5 and 600"),
    ({"set": {"missed_append": "maybe"}}, "true or false"),
    ({"set": {"sharp_questions": False}}, "unknown setting"),
    ({"set": {"colour": "red"}}, "unknown setting"),
    ({"remove_custom": 3}, "no custom rule 3"),
    ({"undo": True}, "nothing to undo"),
    ({"explode": True}, "unknown change"),
])
def test_invalid_changes_rejected_without_touching_config(change, msg):
    new, log, _, hist = apply([change])
    assert new == BASE and hist == []
    assert log[0].startswith("✗") and msg in log[0]


def test_old_global_sharp_questions_dropped_on_next_change():
    new, _, _, _ = apply([{"set": {"grade_timeout_s": 90}}], cfg=dict(BASE, sharp_questions=False))
    assert "sharp_questions" not in new and "sharp_questions" not in config_ops.TOGGLES
    assert "set_deck_sharp" in config_ops.CONFIG_SYSTEM_PROMPT


def test_claude_path_must_be_executable():
    new, log, _, _ = apply([{"set": {"claude_path": "/nope"}}], executable=False)
    assert new["claude_path"] == "/bin/claude" and "not an executable" in log[0]


def test_full_model_id_accepted():
    new, _, _, _ = apply([{"set": {"model": "claude-opus-5-5"}}])
    assert new["models"]["claude"] == "claude-opus-5-5"


def test_custom_add_and_remove():
    new, log, _, _ = apply([{"add_custom": " grade strictly "}, {"add_custom": "worked examples"}])
    assert new["custom"] == ["grade strictly", "worked examples"]
    new, log, _, _ = apply([{"remove_custom": 1}], cfg=new)
    assert new["custom"] == ["worked examples"] and log == ['✓ removed custom rule 1: "grade strictly"']


def test_undo_restores_previous_config():
    history = []
    changed, _, _, _ = apply([{"set": {"model": "opus"}}], history=history)
    restored, log, _, _ = apply([{"undo": True}], cfg=changed, history=history)
    assert restored == BASE and history == [] and log == ["✓ undid the previous change"]


def test_auth_actions_returned_not_applied():
    new, log, auth, hist = apply([{"login": True}])
    assert auth == ["login"] and new == BASE and log == [] and hist == []


def test_parse_config_reply():
    r = config_ops.parse_config_reply('```json\n{"reply":" ok ","changes":[{"set":{"model":"opus"}},"junk"]}\n```')
    assert r == {"reply": "ok", "changes": [{"set": {"model": "opus"}}]}


def test_config_prompt_lists_settings_rules_and_login():
    p = config_ops.config_prompt(dict(BASE, custom=["be strict"]), "logged in (claude.ai)", "use opus")
    assert '"model": "sonnet"' in p and '"codex": ""' in p and "1. be strict" in p and "logged in" in p and p.endswith("User: use opus")


def test_tutor_system_prompt_appends_custom_rules():
    assert grading.system_prompt([]) == grading.SYSTEM_PROMPT
    sp = grading.system_prompt(["grade strictly", " "])
    assert sp.startswith(grading.SYSTEM_PROMPT) and sp.endswith("- grade strictly")


DECKS = {"Biology": "1", "Biology::Cells": "2", "Biology::Cells::Mitochondria": "3",
         "Spanish": "4", "Archive::Cells::Mitochondria": "5"}


def test_deck_chain_outer_to_inner_skips_decks_without_prompt():
    prompts = {"1": "worked examples", "3": "ask for diagrams", "4": "accents"}
    assert config_ops.deck_chain("Biology::Cells::Mitochondria", DECKS, prompts) == [
        ("Biology", "worked examples"), ("Biology::Cells::Mitochondria", "ask for diagrams")]
    assert config_ops.deck_chain("Spanish", DECKS, prompts) == [("Spanish", "accents")]
    assert config_ops.deck_chain("Unknown::Deck", DECKS, prompts) == []


def test_set_and_clear_deck_prompt_keyed_by_id():
    new, log, _, hist = apply([{"set_deck_prompt": {"deck": "spanish", "prompt": "require accents"}}], decks=DECKS)
    assert new["deck_prompts"] == {"4": "require accents"} and log == ['✓ prompt for Spanish: "require accents"']
    new, log, _, _ = apply([{"clear_deck_prompt": "Spanish"}], cfg=new, decks=DECKS)
    assert new["deck_prompts"] == {} and log == ["✓ cleared prompt for Spanish"]


def test_deck_prompt_survives_rename_because_keyed_by_id():
    new, _, _, _ = apply([{"set_deck_prompt": {"deck": "Spanish", "prompt": "accents"}}], decks=DECKS)
    renamed = {"Languages::Spanish": "4"}
    assert config_ops.deck_chain("Languages::Spanish", renamed, new["deck_prompts"]) == [("Languages::Spanish", "accents")]


def test_deck_sharp_override_inherited_innermost_wins():
    cfg = dict(BASE)
    assert config_ops.deck_toggle_source(cfg, "sharp", "Biology::Cells::Mitochondria", DECKS) == (True, None)  # default on
    new, log, _, _ = apply([{"set_deck_sharp": {"deck": "Biology", "on": False}}], cfg=cfg, decks=DECKS)
    assert new["deck_sharp"] == {"1": False} and log == ["✓ Sharp questions for Biology and its subdecks: off"]
    assert config_ops.deck_toggle_source(new, "sharp", "Biology::Cells::Mitochondria", DECKS) == (False, "Biology")
    assert config_ops.deck_toggle_on(new, "sharp", "Spanish", DECKS) is True
    new, _, _, _ = apply([{"set_deck_sharp": {"deck": "Biology::Cells", "on": "on"}}], cfg=new, decks=DECKS)
    assert config_ops.deck_toggle_source(new, "sharp", "Biology::Cells::Mitochondria", DECKS) == (True, "Biology::Cells")
    new, log, _, _ = apply([{"set_deck_sharp": {"deck": "Biology", "on": None}}], cfg=new, decks=DECKS)
    assert new["deck_sharp"] == {"2": True} and log == ["✓ Sharp questions for Biology: follow parent (default on)"]


def test_deck_sharp_parent_change_makes_subdecks_follow_others_kept():
    cfg = dict(BASE, deck_sharp={"2": True, "3": False, "4": False, "5": True})
    new, log, _, _ = apply([{"set_deck_sharp": {"deck": "Biology", "on": False}}], cfg=cfg, decks=DECKS)
    assert new["deck_sharp"] == {"1": False, "4": False, "5": True}
    assert "2 subdeck setting(s) now follow it" in log[0]
    new, _, _, _ = apply([{"set_deck_sharp": {"deck": "Biology::Cells::Mitochondria", "on": True}}], cfg=new, decks=DECKS)
    assert new["deck_sharp"]["1"] is False and new["deck_sharp"]["3"] is True  # a subdeck exception keeps the parent


def test_deck_sharp_change_flips_effective_value():
    cfg = dict(BASE, deck_sharp={"1": False})
    assert config_ops.deck_toggle_change(cfg, "sharp", "Biology::Cells", DECKS) == {
        "set_deck_sharp": {"deck": "Biology::Cells", "on": True}}
    assert config_ops.deck_toggle_change(cfg, "sharp", "Spanish", DECKS) == {"set_deck_sharp": {"deck": "Spanish", "on": False}}


def test_deck_ai_toggle_independent_and_cascades():
    cfg = dict(BASE, deck_sharp={"1": False}, deck_ai={"3": False})
    new, log, _, _ = apply([{"set_deck_ai": {"deck": "Biology", "on": False}}], cfg=cfg, decks=DECKS)
    assert new["deck_ai"] == {"1": False} and new["deck_sharp"] == {"1": False}
    assert log[0].startswith("✓ AI Study for Biology and its subdecks: off")
    assert config_ops.deck_toggle_on(new, "ai", "Biology::Cells::Mitochondria", DECKS) is False
    assert config_ops.deck_toggle_on(new, "ai", "Spanish", DECKS) is True
    assert config_ops.deck_toggle_change(new, "ai", "Spanish", DECKS) == {"set_deck_ai": {"deck": "Spanish", "on": False}}
    assert "set_deck_ai" in config_ops.CONFIG_SYSTEM_PROMPT


def test_prune_drops_missing_decks_from_prompts_and_sharp():
    cfg = dict(BASE, deck_prompts={"1": "x", "9": "y"}, deck_sharp={"9": False, "4": True}, deck_ai={"9": False})
    out = config_ops.prune_deck_prompts(cfg, {"1", "4"})
    assert out["deck_prompts"] == {"1": "x"} and out["deck_sharp"] == {"4": True} and out["deck_ai"] == {}


def test_config_prompt_shows_deck_sharp():
    cfg = dict(BASE, deck_sharp={"1": False})
    p = config_ops.config_prompt(cfg, "ok", "hi", decks=DECKS, selected="Biology::Cells")
    assert "- Biology: Sharp questions off" in p and "Sharp questions off" in p


@pytest.mark.parametrize("change,msg", [
    ({"set_deck_sharp": {"deck": "Spanish", "on": "maybe"}}, "true or false"),
    ({"set_deck_sharp": {"deck": "Spanish", "on": None}}, "no Sharp questions setting"),
    ({"set_deck_prompt": {"deck": "Mitochondria", "prompt": "x"}}, "ambiguous"),
    ({"set_deck_prompt": {"deck": "Nope", "prompt": "x"}}, "no deck named"),
    ({"set_deck_prompt": {"deck": "Spanish", "prompt": " "}}, "empty deck prompt"),
    ({"clear_deck_prompt": "Spanish"}, "has no prompt"),
])
def test_bad_deck_changes_rejected(change, msg):
    new, log, _, hist = apply([change], decks=DECKS)
    assert new == BASE and log[0].startswith("✗") and msg in log[0]


def test_unique_leaf_name_resolves():
    new, _, _, _ = apply([{"set_deck_prompt": {"deck": "cells", "prompt": "x"}}], decks=DECKS)
    assert new["deck_prompts"] == {"2": "x"}


def test_prune_drops_deleted_decks():
    cfg = dict(BASE, deck_prompts={"4": "a", "99": "gone"})
    assert config_ops.prune_deck_prompts(cfg, {"4"})["deck_prompts"] == {"4": "a"}


def test_config_prompt_shows_selected_deck_chain():
    cfg = dict(BASE, deck_prompts={"1": "examples", "3": "diagrams"})
    p = config_ops.config_prompt(cfg, "ok", "hi", DECKS, "Biology::Cells::Mitochondria")
    assert "Selected deck: Biology::Cells::Mitochondria" in p
    assert "  Biology: examples\n  Biology::Cells::Mitochondria: diagrams" in p
    assert "- Spanish" not in p and "Spanish" in p  # listed as a deck, no prompt


def test_card_prompts_carry_deck_rules():
    rules = [("Biology", "scenarios"), ("Biology::Cells::Mitochondria", "code")]
    ask = grading.ask_prompt("Q", "A", rules)
    grade = grading.grade_prompt("Q", [], "A", ["mine"], rules)
    for p in (ask, grade):
        assert "Deck rules (outer → inner):\n- Biology: scenarios\n- Biology::Cells::Mitochondria: code" in p
    assert "Deck rules" not in grading.ask_prompt("Q", "A")


@pytest.mark.parametrize("value", ["", "auto", " AUTO "])
def test_claude_path_auto_values_reset_to_autodetect(value):
    new, log, _, _ = apply([{"set": {"claude_path": value}}], executable=False)
    assert new["claude_path"] == ""


def test_toggle_flips_and_defaults_on():
    assert config_ops.toggle_change({"missed_append": True}, "missed_append") == {"set": {"missed_append": False}}
    assert config_ops.toggle_change({}, "missed_append") == {"set": {"missed_append": False}}  # missing = on
    assert config_ops.toggle_on({}, "missed_append") is True
    with pytest.raises(KeyError):
        config_ops.toggle_change({}, "provider")
    for key, (label, tip) in config_ops.TOGGLES.items():
        assert key in config_ops.SETTINGS and label and len(tip) >= 2 and all(len(line) > 20 for line in tip)
    new, log, _, hist = apply([config_ops.toggle_change(BASE, "missed_append")])
    assert new["missed_append"] is False and log == ["✓ missed_append: true → false"] and hist == [BASE]
