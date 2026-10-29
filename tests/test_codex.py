import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from addon import config_ops, session  # noqa: E402
from addon.grading import parse_json_reply  # noqa: E402
from addon.session import CodexBackend, SessionError, parse_codex_output  # noqa: E402
from fakes import FAKE_CLAUDE, FAKE_CODEX, make_exe  # noqa: E402

FAKE = [sys.executable, os.path.join(os.path.dirname(__file__), "fake_codex.py")]


@pytest.fixture
def codex(tmp_path):
    b = CodexBackend(FAKE, str(tmp_path), lambda fn: fn(), "SYSTEM PROMPT")
    yield b
    b.close()


def call(b, prompt, timeout=10):
    done, out = threading.Event(), {}
    b.request(1, prompt, parse_json_reply, timeout, lambda cid, r, e: (out.update(result=r, err=e), done.set()))
    assert done.wait(15), "callback never fired"
    return out


def test_last_agent_message_is_the_answer_and_system_prompt_is_prepended(codex):
    r = call(codex, "grade this")
    assert r["err"] is None and r["result"] == {"echo": "grade this", "system": True}


def test_bad_json_retry_resends_original_prompt(codex):
    r = call(codex, "BADJSON grade")
    assert r["err"] is None and "not valid JSON" in r["result"]["echo"]


@pytest.mark.parametrize("prompt,kind,text", [
    ("ERROREVENT", "error", "stream disconnected"),
    ("TURNFAILED", "error", "overloaded"),
    ("LIMIT", "limit", "usage limit"),
    ("EXIT1", "error", "not logged in"),
    ("NOANSWER", "error", "no answer"),
])
def test_failures_map_to_session_errors(codex, prompt, kind, text):
    err = call(codex, prompt)["err"]
    assert err.kind == kind and text in err.message


def test_timeout_kills_the_call(codex):
    assert call(codex, "SLEEP:3", timeout=0.5)["err"].kind == "timeout"
    assert call(codex, "next")["result"]["echo"] == "next"


def test_missing_binary_is_unavailable(tmp_path):
    b = CodexBackend(["/nonexistent/codex"], str(tmp_path), lambda fn: fn(), "S")
    try:
        assert call(b, "x")["err"].kind == "unavailable"
    finally:
        b.close()


def test_stop_drops_inflight_reply(codex):
    fired = []
    codex.request(1, "SLEEP:1", parse_json_reply, 10, lambda *a: fired.append(a))
    import time
    time.sleep(0.3)
    codex.stop()
    assert call(codex, "after")["result"]["echo"] == "after"
    assert fired == []


def test_parse_codex_output_ignores_non_json_lines():
    out = 'warning: blah\n{"type":"item.completed","item":{"type":"agent_message","text":"{}"}}\n'
    assert parse_codex_output(out, "", 0) == "{}"
    with pytest.raises(SessionError):
        parse_codex_output("", "boom", 2)


def test_codex_command_is_isolated_and_reads_stdin():
    cmd = session.build_codex_command("/x/codex", "", "/tmp/w")
    for flag in ("--ephemeral", "--ignore-user-config", "--ignore-rules", "shell_tool", 'web_search="disabled"'):
        assert flag in cmd
    assert cmd[cmd.index("-s") + 1] == "read-only" and cmd[-1] == "-" and "-m" not in cmd
    assert session.build_codex_command("/x/codex", "gpt-x", "/tmp/w")[-5:-3] == ["-m", "gpt-x"]


def test_web_commands_add_only_web_search():
    """The chat gets read-only tools (files, web); nothing that writes or runs opens up, and grading's commands stay closed."""
    codex = session.build_codex_command("/x/codex", "", "/tmp/w", web=True)
    assert 'web_search="live"' in codex and 'web_search="disabled"' not in codex
    assert codex[codex.index("-s") + 1] == "read-only" and "shell_tool" in codex
    claude = session.build_command("/x/claude", "", "S", web=True)
    assert claude[claude.index("--tools") + 1] == "Read,Grep,Glob,WebSearch,WebFetch,Agent"
    assert claude[claude.index("--allowedTools") + 1] == "Read,Grep,Glob,WebSearch,WebFetch,Agent"  # nobody can answer a prompt
    assert claude[claude.index("--setting-sources") + 1] == "" and "--safe-mode" in claude
    plain = session.build_command("/x/claude", "", "S")
    assert plain[plain.index("--tools") + 1] == "" and "--allowedTools" not in plain


def test_claude_command_omits_model_when_default():
    assert "--model" not in session.build_command("/x/claude", "", "S")
    assert session.build_command("/x/claude", "opus", "S")[-4:-2] == ["--model", "opus"]


@pytest.mark.parametrize("web", [False, True])
def test_claude_commands_use_medium_effort(web):
    cmd = session.build_command("/x/claude", "claude-example-model[1m]", "S", web=web)
    assert cmd.count("--effort") == 1 and cmd[cmd.index("--effort") + 1] == "medium"
    assert "--effort" not in session.build_codex_command("/x/codex", "", "/tmp/w", web=web)


def test_claude_command_keeps_custom_model_model_id_and_context_suffix():
    model = "claude-example-model[1m]"
    cmd = session.build_command("/x/claude", model, "S")
    assert cmd[cmd.index("--model") + 1] == model


def test_claude_system_prompt_goes_in_a_file(tmp_path):
    """Not an argument: Windows' cmd.exe (npm's claude.cmd) cuts arguments at the first newline."""
    c = session.make_backend({"claude_path": "/x/claude"}, "line one\nline two → ✓", str(tmp_path), lambda f: f())
    try:
        assert "--system-prompt" not in c._cmd
        path = c._cmd[c._cmd.index("--system-prompt-file") + 1]
        with open(path, encoding="utf-8") as f:
            assert f.read() == "line one\nline two → ✓"
        assert session.system_prompt_file(str(tmp_path), "line one\nline two → ✓") == path  # same prompt, same file
    finally:
        c.close()


def test_make_backend_scopes_study_to_card_but_preserves_chat(tmp_path):
    study = session.make_backend({"claude_path": "/x/claude"}, "S", str(tmp_path), lambda f: f())
    chat = session.make_backend({"claude_path": "/x/claude"}, "S", str(tmp_path), lambda f: f(), web=True)
    try:
        assert study._card_scoped is True and chat._card_scoped is False
    finally:
        study.close()
        chat.close()


def test_codex_round_trips_non_ascii(codex):
    out = call(codex, "Explain → in \\(O(n \\log n)\\) — café, 中文 ✓")
    assert out["err"] is None and out["result"]["echo"] == "Explain → in \\(O(n \\log n)\\) — café, 中文 ✓"


def test_make_backend_picks_provider(tmp_path):
    b = session.make_backend({"provider": "codex", "codex_path": "/x/codex", "models": {"codex": "gpt-x"}},
                             "S", str(tmp_path), lambda f: f())
    c = session.make_backend({"claude_path": "/x/claude"}, "S", str(tmp_path), lambda f: f())
    try:
        assert isinstance(b, CodexBackend) and b._cmd[0] == "/x/codex" and "gpt-x" in b._cmd
        assert isinstance(c, session.ClaudeSession) and c._cmd[0] == "/x/claude"
    finally:
        b.close()
        c.close()


@pytest.mark.parametrize("provider,rc,out,expected", [
    ("codex", 0, "Logged in using ChatGPT\n", (True, "Logged in using ChatGPT")),
    ("codex", 1, "Not logged in\n", (False, "logged out")),
    ("claude", 0, '{"loggedIn": true, "authMethod": "claude.ai"}', (True, "logged in (claude.ai)")),
    ("claude", 0, '{"loggedIn": false}', (False, "logged out")),
])
def test_parse_auth_status(provider, rc, out, expected):
    assert session.parse_auth_status(provider, rc, out) == expected


def test_auth_commands():
    assert session.auth_status_command("codex", "c") == ["c", "login", "status"]
    assert session.auth_command("codex", "c", "logout") == ["c", "logout"]
    assert session.auth_command("claude", "c", "login") == ["c", "auth", "login"]


BASE = {"provider": "claude", "models": {"claude": "sonnet", "codex": ""}, "custom": []}


def apply(changes, cfg=None):
    new, log, _ = config_ops.apply_changes(dict(cfg or BASE), changes, [], lambda p: True)
    return new, log


def test_each_provider_remembers_its_own_model():
    new, log = apply([{"set": {"provider": "codex"}}, {"set": {"model": "gpt-5.5"}}])
    assert new["models"] == {"claude": "sonnet", "codex": "gpt-5.5"}
    assert log == ["✓ provider: claude → codex (model: default)", "✓ codex model: default → gpt-5.5"]
    back, log = apply([{"set": {"provider": "claude"}}], cfg=new)
    assert session.model_for(back) == "sonnet" and log == ["✓ provider: codex → claude (model: sonnet)"]


def test_model_is_validated_against_the_provider_set_in_the_same_change():
    new, _ = apply([{"set": {"model": "gpt-5.5", "provider": "codex"}}])
    assert new["provider"] == "codex" and new["models"]["codex"] == "gpt-5.5" and new["models"]["claude"] == "sonnet"
    new, log = apply([{"set": {"provider": "codex", "model": "opus"}}])
    assert new["models"]["codex"] == "" and any("not an OpenAI model id" in line for line in log)


def test_model_per_provider_and_old_cache_keys_dropped():
    cfg = {"provider": "codex", "models": {"codex": "gpt-5.5"}, "custom": [],
           "resolved_models": {"codex:": "x"}, "last_good": {"codex": "1.0.0"}}
    assert session.model_for(cfg) == "gpt-5.5" and session.model_for(cfg, "claude") == ""
    new, _ = apply([{"add_custom": "x"}], cfg=cfg)
    assert new["models"] == {"claude": "", "codex": "gpt-5.5"}
    assert "resolved_models" not in new and "last_good" not in new  # learned facts live in state.py now
    assert session.model_for({"custom": []}) == ""  # nothing set: provider default


@pytest.mark.parametrize("value", ["gemini", "openai"])
def test_unknown_provider_rejected(value):
    new, log = apply([{"set": {"provider": value}}])
    assert new == BASE and "unknown provider" in log[0]


def test_model_default_keyword():
    new, log = apply([{"set": {"model": "default"}}])
    assert new["models"]["claude"] == "" and log == ["✓ claude model: sonnet → default"]


def _fake_cli(tmp_path, body):
    return make_exe(tmp_path, "cli", body=body)


def test_read_auth_status_codex_reads_stderr(tmp_path):
    # real codex 0.152.0 prints "Logged in using ChatGPT" on stderr with an empty stdout
    path = _fake_cli(tmp_path, 'sys.stderr.write("Logged in using ChatGPT\\n")')
    assert session.read_auth_status("codex", path) == (True, "Logged in using ChatGPT")


def test_read_auth_status_claude_reads_stdout_json(tmp_path):
    path = _fake_cli(tmp_path, 'print(\'{"loggedIn": true, "authMethod": "claude.ai"}\')')
    assert session.read_auth_status("claude", path) == (True, "logged in (claude.ai)")


def _exe(tmp_path, name, target):
    return make_exe(tmp_path, name, target)


def test_probe_model_reads_codex_header(tmp_path):
    name = session.probe_model("codex", _exe(tmp_path, "codex", FAKE_CODEX), "", str(tmp_path))
    assert name == "fake-codex-model" and session.resolved_model("codex", "") == "fake-codex-model"


def test_probe_model_reads_claude_init(tmp_path):
    name = session.probe_model("claude", _exe(tmp_path, "claude", FAKE_CLAUDE), "sonnet", str(tmp_path))
    assert name == "fake-claude-model" and session.resolved_model("claude", "sonnet") == "fake-claude-model"


def test_startup_check_also_starts_the_chat_command(tmp_path):
    """The self-check runs the web-enabled chat command too, so a CLI that rejects its flags is caught on open."""
    for name, fake, model in (("claude", FAKE_CLAUDE, "fake-claude-model"), ("codex", FAKE_CODEX, "fake-codex-model")):
        assert session.startup_check(name, _exe(tmp_path, name, fake), str(tmp_path)) == model


def test_probe_model_fails_cleanly(tmp_path):
    with pytest.raises(SessionError):
        session.probe_model("codex", make_exe(tmp_path, "x", body="sys.stdin.read()"), "", str(tmp_path), timeout=5)


def test_real_claude_calls_record_the_model(tmp_path):
    s = session.ClaudeSession([sys.executable, FAKE_CLAUDE], str(tmp_path), lambda f: f(), "opus")
    try:
        done = threading.Event()
        s.request(1, "hi", parse_json_reply, 5, lambda *a: done.set())
        assert done.wait(10) and session.resolved_model("claude", "opus") == "fake-claude-model"
    finally:
        s.close()


def test_list_models_codex_uses_visible_catalog_in_priority_order(tmp_path):
    assert session.list_models("codex", _exe(tmp_path, "codex", FAKE_CODEX), str(tmp_path)) == [
        ("model-a", "model-a"), ("model-b", "model-b")]


def test_list_models_claude_uses_catalog_including_custom_model(tmp_path):
    opts = session.list_models("claude", _exe(tmp_path, "claude", FAKE_CLAUDE), str(tmp_path))
    assert opts == [("sonnet", "Sonnet"), ("claude-example-model[1m]", "Example gateway model 1M")]


def test_claude_catalog_sends_only_initialize_and_ignores_unrelated_events(tmp_path):
    path = make_exe(tmp_path, "catalog", body='''
import json
assert "--safe-mode" in sys.argv and "--strict-mcp-config" in sys.argv
assert sys.argv[sys.argv.index("--setting-sources") + 1] == ""
assert sys.argv[sys.argv.index("--tools") + 1] == ""
request = json.loads(sys.stdin.readline())
assert request["type"] == "control_request" and request["request"] == {"subtype": "initialize"}
sys.stderr.write("diagnostic\\n" * 100000)
sys.stderr.flush()
print("[]", flush=True)
response = {"subtype": "success", "request_id": "unrelated", "response": {"models": []}}
print(json.dumps({"type": "control_response", "response": response}), flush=True)
response.update(request_id=request["request_id"], response={"models": [{"value": "claude-custom"}]})
print(json.dumps({"type": "control_response", "response": response}), flush=True)
assert not sys.stdin.readline(), "model discovery must not send a user prompt"
''')
    assert session.list_models("claude", path, str(tmp_path), timeout=5) == [("claude-custom", "claude-custom")]


def test_claude_catalog_loads_only_picker_and_allowlist(tmp_path, monkeypatch):
    import json
    config_dir = tmp_path / "cli-config"
    config_dir.mkdir()
    model = "claude-example-model[1m]"
    picker = {"options": [{"model": model, "label": "Example gateway model 1M"}], "replaceBuiltInOptions": True}
    (config_dir / "settings.json").write_text(json.dumps({
        "modelPicker": picker, "availableModels": [model],
        "env": {"UNRELATED_SETTING": "must not load"}, "hooks": {"SessionStart": []},
        "enabledPlugins": {"example": True},
    }), encoding="utf-8")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))
    path = make_exe(tmp_path, "catalog", body='''
import json
with open(sys.argv[sys.argv.index("--settings") + 1], encoding="utf-8") as f:
    settings = json.load(f)
assert set(settings) == {"modelPicker", "availableModels"}
assert settings["modelPicker"]["replaceBuiltInOptions"] is True
assert "--safe-mode" in sys.argv
assert sys.argv[sys.argv.index("--setting-sources") + 1] == ""
request = json.loads(sys.stdin.readline())
models = [{"value": m["model"], "displayName": m["label"]} for m in settings["modelPicker"]["options"]
          if m["model"] in settings["availableModels"]]
print(json.dumps({"type": "control_response", "response": {
    "subtype": "success", "request_id": request["request_id"], "response": {"models": models}}}), flush=True)
''')
    assert session.list_models("claude", path, str(tmp_path)) == [(model, "Example gateway model 1M")]
    assert not list(tmp_path.glob("models-*.json"))  # temporary picker settings are removed after discovery
    assert "--settings" not in session.build_command(path, model, "S")  # studying still loads no user settings


@pytest.mark.parametrize("contents", ["invalid json", "[]", "{}"])
def test_claude_catalog_works_with_invalid_or_empty_settings(tmp_path, monkeypatch, contents):
    config_dir = tmp_path / "cli-config"
    config_dir.mkdir()
    (config_dir / "settings.json").write_text(contents, encoding="utf-8")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))
    assert session.list_models("claude", _exe(tmp_path, "claude", FAKE_CLAUDE), str(tmp_path))


@pytest.mark.parametrize("web", [False, True])
def test_claude_requests_and_probes_use_configured_transport(tmp_path, monkeypatch, web):
    import json
    config_dir = tmp_path / "cli-config"
    config_dir.mkdir()
    (config_dir / "settings.json").write_text(json.dumps({"env": {
        "ANTHROPIC_BASE_URL": "http://localhost:12345", "ANTHROPIC_API_KEY": "test-only",
        "ANTHROPIC_AUTH_TOKEN": "", "UNRELATED_SETTING": "must not load",
    }}), encoding="utf-8")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))
    for key in ("ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY", "UNRELATED_SETTING"):
        monkeypatch.delenv(key, raising=False)  # Anki launched from the Dock
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "inherited-test-token")
    body = '''
import os
import runpy
assert os.environ["ANTHROPIC_BASE_URL"] == "http://localhost:12345"
assert os.environ["ANTHROPIC_API_KEY"] == "test-only"
assert os.environ["ANTHROPIC_AUTH_TOKEN"] == ""
assert "UNRELATED_SETTING" not in os.environ
assert "--safe-mode" in sys.argv and "test-only" not in sys.argv and "--settings" not in sys.argv
assert sys.argv[sys.argv.index("--effort") + 1] == "medium"
'''
    path = make_exe(tmp_path, "transport", body=body + f"\nrunpy.run_path({FAKE_CLAUDE!r}, run_name='__main__')")
    cfg = {"claude_path": path, "models": {"claude": "claude-example-model[1m]"}}
    backend = session.make_backend(cfg, "S", str(tmp_path), lambda f: f(), web=web)
    try:
        result = call(backend, "routing check")
        assert result["err"] is None and result["result"]["echo"] == "routing check"
    finally:
        backend.close()
    assert session.probe_model("claude", path, session.model_for(cfg), str(tmp_path)) == "fake-claude-model"


def test_claude_env_preserves_inherited_transport_without_config(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://localhost:12345")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-only")
    assert session._claude_env() == dict(os.environ)


def test_claude_catalog_error_is_reported_without_waiting_for_timeout(tmp_path):
    import time
    path = make_exe(tmp_path, "catalog", body='''
import json
request = json.loads(sys.stdin.readline())
print(json.dumps({"type": "control_response", "response": {
    "subtype": "error", "request_id": request["request_id"], "error": "catalog unavailable"}}), flush=True)
sys.stdin.read()
''')
    started = time.monotonic()
    with pytest.raises(SessionError, match="catalog unavailable"):
        session.list_models("claude", path, str(tmp_path), timeout=10)
    assert time.monotonic() - started < 5


def test_settings_prompt_carries_model_in_use_and_no_guessing_rule():
    p = config_ops.settings_context({"provider": "codex", "models": {"codex": ""}}, "ok", model_in_use="gpt-5.6-sol")
    assert '"model": "(provider default)"' in p and '"model in use": "gpt-5.6-sol"' in p
    assert "Never list, guess or recommend model names" in config_ops.SETTINGS_RULES
