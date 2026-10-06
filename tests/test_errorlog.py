import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from addon import errorlog  # noqa: E402


def _raise_in(folder: str, name: str):
    """An error whose traceback has a frame in a file under `folder`."""
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    with open(path, "w") as f:
        f.write("def boom():\n    raise ValueError('oops')\n")
    ns = {}
    exec(compile(open(path).read(), path, "exec"), ns)
    try:
        ns["boom"]()
    except ValueError:
        return sys.exc_info()


def test_logs_only_errors_through_the_addon(tmp_path):
    mine, other, log = str(tmp_path / "addon"), str(tmp_path / "other"), str(tmp_path / "user_files" / "error.log")
    assert errorlog.log_exception(log, *_raise_in(other, "x.py"), dirs=(mine,)) is False
    assert not os.path.exists(log)
    assert errorlog.log_exception(log, *_raise_in(mine, "x.py"), dirs=(mine,)) is True
    text = open(log, encoding="utf-8").read()
    assert "ValueError: oops" in text and "x.py" in text and text.startswith("--- ")
    errorlog.log_exception(log, *_raise_in(mine, "x.py"), dirs=(mine,))
    assert open(log, encoding="utf-8").read().count("ValueError: oops") == 2  # appended


def test_log_starts_over_when_too_big(tmp_path, monkeypatch):
    mine, log = str(tmp_path / "addon"), str(tmp_path / "error.log")
    monkeypatch.setattr(errorlog, "MAX_BYTES", 10)
    exc = _raise_in(mine, "x.py")
    errorlog.log_exception(log, *exc, dirs=(mine,))
    errorlog.log_exception(log, *exc, dirs=(mine,))
    assert open(log, encoding="utf-8").read().count("ValueError: oops") == 1


def test_install_wraps_both_hooks_and_still_calls_the_old_ones(tmp_path, monkeypatch):
    log = str(tmp_path / "error.log")
    seen = []
    monkeypatch.setattr(sys, "excepthook", lambda *a: seen.append("main"))
    monkeypatch.setattr(threading, "excepthook", lambda a: seen.append("thread"))
    errorlog.install(log)
    exc = _raise_in(str(tmp_path), "x.py")
    sys.excepthook(*exc)  # not the add-on's code: nothing logged, old hook still runs
    threading.excepthook(threading.ExceptHookArgs((exc[0], exc[1], exc[2], None)))
    assert seen == ["main", "thread"] and not os.path.exists(log)
