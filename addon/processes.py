"""Own every add-on CLI process and background job across profile and app shutdown. No Anki imports."""

import atexit
import os
import signal
import subprocess
import threading

_lock = threading.RLock()
_local = threading.local()
_processes = set()
_generation = 0
_active = True


def generation() -> int:
    with _lock:
        return _generation


def current(token=None) -> bool:
    with _lock:
        return _active and (token if token is not None else getattr(_local, "generation", _generation)) == _generation


def resume(*args):
    global _active
    with _lock:
        _active = True


def background(work):
    """Keep a job's profile generation even if another profile opens before the job finishes."""
    with _lock:
        token = getattr(_local, "generation", _generation)

    def run():
        _local.generation = token
        if current():
            work()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def on_main(dispatch, callback):
    token = getattr(_local, "generation", _generation)

    def fire():
        if current(token):
            callback()

    if current(token):
        dispatch(fire)


def popen(*args, **kwargs):
    with _lock:
        if not current():
            raise RuntimeError("AI jobs stopped because the profile is closed")
        if os.name != "nt":
            kwargs["start_new_session"] = True  # only our own process group may be killed
        proc = subprocess.Popen(*args, **kwargs)
        _processes.add(proc)
        return proc


def terminate(proc):
    """Kill the owned process tree, including POSIX descendants whose parent already exited."""
    proc.poll()  # reap an exited parent before signalling its group; descendants may still be alive
    if os.name == "nt":
        if proc.poll() is None:
            result = subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True,
                                    encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode and proc.poll() is None:
                raise OSError(result.stderr or "Could not stop CLI process tree")
    else:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
    finally:
        if os.name != "nt":  # parent exit does not prove its children obeyed SIGTERM
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        proc.wait(timeout=3)
        try:  # signal first: closing stdin can block behind a writer when the CLI is not reading
            if proc.stdin is not None:
                proc.stdin.close()
        except (OSError, ValueError):
            pass
        with _lock:
            _processes.discard(proc)


def run(args, *, capture_output=False, timeout=None, **kwargs):
    """subprocess.run with ownership and tree cleanup on completion, timeout and shutdown."""
    if capture_output:
        kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    proc = popen(args, **kwargs)
    try:
        out, err = proc.communicate(timeout=timeout)
        return subprocess.CompletedProcess(args, proc.returncode, out, err)
    finally:
        terminate(proc)


def shutdown():
    global _active, _generation
    with _lock:
        if _active:
            _active = False
            _generation += 1
        procs = list(_processes)
    error = None
    for proc in procs:
        try:
            terminate(proc)
        except (OSError, subprocess.TimeoutExpired) as e:
            error = e  # attempt every owner, then report any cleanup failure
    if error is not None:
        raise error


atexit.register(shutdown)
