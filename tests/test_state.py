import json

import pytest

from addon import state


@pytest.mark.parametrize("contents", ["[]", "null", "42", '"text"', '{"ui": []}'])
def test_invalid_state_shapes_do_not_prevent_startup(tmp_path, contents):
    path = tmp_path / "state.json"
    path.write_text(contents, encoding="utf-8")
    state.reset(str(path))
    assert state.get("ui", "ai_study") is None
    state.put("ui", "ai_study", True)
    assert json.loads(path.read_text(encoding="utf-8")) == {"ui": {"ai_study": True}}


def test_invalid_state_section_does_not_drop_valid_sections(tmp_path):
    path = tmp_path / "state.json"
    path.write_text('{"ui": [], "models": {"claude:": "example-model"}}', encoding="utf-8")
    state.reset(str(path))
    assert state.get("ui", "ai_study") is None
    assert state.get("models", "claude:") == "example-model"
