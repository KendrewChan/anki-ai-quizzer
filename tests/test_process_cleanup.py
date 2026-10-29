import os
import signal
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from addon import processes, session


def running(pid):
    result = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    return bool(result.stdout.strip()) and not result.stdout.strip().startswith("Z")


@pytest.mark.skipif(os.name == "nt", reason="POSIX process groups; Windows uses taskkill /T")
@pytest.mark.parametrize("parent_exits", [False, True])
def test_terminate_kills_descendant_even_after_parent_exits(tmp_path, parent_exits):
    child_code = "import signal, threading; signal.signal(signal.SIGTERM, signal.SIG_IGN); print('ready', flush=True); threading.Event().wait(30)"
    parent_code = (
        "import subprocess, sys, threading; "
        f"child = subprocess.Popen([sys.executable, '-c', {child_code!r}], stdout=subprocess.PIPE, text=True); "
        "child.stdout.readline(); print(child.pid, flush=True); "
        + ("" if parent_exits else "threading.Event().wait(30)")
    )
    proc = subprocess.Popen([sys.executable, "-c", parent_code], cwd=tmp_path, start_new_session=True,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    child_pid = int(proc.stdout.readline())
    try:
        if parent_exits:
            proc.wait(timeout=5)
        session._terminate(proc)
        for _ in range(50):
            if not running(child_pid):
                break
            threading.Event().wait(0.02)
        assert not running(child_pid), "CLI descendant survived cleanup"
        assert proc.poll() is not None
    finally:
        if running(child_pid):
            os.kill(child_pid, signal.SIGKILL)
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=5)


@pytest.mark.parametrize("returncode", [0, 1])
def test_windows_cleanup_targets_owned_process_tree(monkeypatch, returncode):
    calls = []
    monkeypatch.setattr(processes, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0, raising=False)

    def taskkill(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=returncode, stderr="could not stop process")

    monkeypatch.setattr(subprocess, "run", taskkill)
    class Process:
        pid, stdin = 123, None

        def poll(self):
            return None

        def wait(self, timeout):
            return 0

    if returncode:
        with pytest.raises(OSError, match="could not stop process"):
            processes.terminate(Process())
    else:
        processes.terminate(Process())
    assert calls == [["taskkill", "/F", "/T", "/PID", "123"]]


def test_close_is_terminal_and_worker_stops(tmp_path):
    backend = session.ClaudeSession(["/nonexistent/claude"], str(tmp_path), lambda fn: fn())
    backend.close()
    backend.request(1, "too late", lambda text: {}, 1, lambda *args: None)
    backend._worker.join(timeout=2)
    assert not backend._worker.is_alive()
    assert backend._jobs.empty()


def test_cleanup_unblocks_a_writer_when_cli_is_not_reading(tmp_path):
    proc = processes.popen([sys.executable, "-c", "import threading; threading.Event().wait(30)"],
                           cwd=tmp_path, stdin=subprocess.PIPE, text=True)
    writing, stopped = threading.Event(), threading.Event()

    def write():
        writing.set()
        try:
            proc.stdin.write("x" * 1000000)
            proc.stdin.flush()
        except (OSError, ValueError):
            pass

    writer = processes.background(write)
    assert writing.wait(2)
    stopper = processes.background(lambda: (processes.terminate(proc), stopped.set()))
    try:
        assert stopped.wait(5), "cleanup blocked behind the stdin writer"
        writer.join(timeout=2)
        assert not writer.is_alive() and proc.poll() is not None
    finally:
        if proc.poll() is None:
            proc.kill()
        writer.join(timeout=2)
        stopper.join(timeout=2)
        processes.terminate(proc)


def test_shutdown_kills_tracked_jobs_and_can_open_another_profile(tmp_path):
    proc = processes.popen([sys.executable, "-c", "import threading; threading.Event().wait(30)"], cwd=tmp_path)
    token = processes.generation()
    try:
        processes.shutdown()
        processes.shutdown()  # repeated profile/app shutdown is harmless
        assert proc.poll() is not None and not processes._processes
        with pytest.raises(RuntimeError, match="profile is closed"):
            processes.popen(["/nonexistent/cli"])
        processes.resume()
        assert not processes.current(token)
        result = processes.run([sys.executable, "-c", "print('ok')"], capture_output=True, text=True)
        assert result.returncode == 0 and result.stdout.strip() == "ok"
        assert not processes._processes
    finally:
        processes.resume()
        processes.terminate(proc)


def test_stale_background_job_cannot_spawn_or_call_back_after_profile_switch():
    ready, release = threading.Event(), threading.Event()
    results, callbacks = [], []

    def work():
        ready.set()
        release.wait(5)
        try:
            processes.popen(["/nonexistent/cli"])
        except RuntimeError:
            results.append("cancelled")
        processes.on_main(lambda fn: fn(), lambda: callbacks.append("late callback"))

    worker = processes.background(work)
    try:
        assert ready.wait(2)
        processes.shutdown()
        processes.resume()
        release.set()
        worker.join(timeout=2)
        assert not worker.is_alive()
        assert results == ["cancelled"] and callbacks == []
    finally:
        release.set()
        worker.join(timeout=2)
        processes.resume()


def test_already_dispatched_callback_is_invalidated_on_profile_close():
    queued, fired = [], []
    processes.on_main(queued.append, lambda: fired.append(True))
    try:
        processes.shutdown()
        processes.resume()
        queued[0]()
        assert fired == []
    finally:
        processes.resume()


def test_shutdown_attempts_every_process_and_reports_cleanup_failure(monkeypatch):
    first, second = object(), object()
    attempted = []
    monkeypatch.setattr(processes, "_processes", {first, second})

    def terminate(proc):
        attempted.append(proc)
        if proc is first:
            raise OSError("could not stop process")
        processes._processes.discard(proc)

    monkeypatch.setattr(processes, "terminate", terminate)
    try:
        with pytest.raises(OSError, match="could not stop process"):
            processes.shutdown()
        assert set(attempted) == {first, second}
        attempted.clear()
        with pytest.raises(OSError):
            processes.shutdown()  # a later app-exit cleanup retries the remaining owner
        assert attempted == [first]
    finally:
        processes._processes.clear()
        processes.resume()


def test_run_timeout_removes_process_from_registry():
    with pytest.raises(subprocess.TimeoutExpired):
        processes.run([sys.executable, "-c", "import threading; threading.Event().wait(30)"], timeout=0.1)
    assert not processes._processes
