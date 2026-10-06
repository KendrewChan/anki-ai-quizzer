"""Keeps a copy of this add-on's Python errors in user_files/error.log.

Anki only shows an error in a dialog and forgets it; this appends the traceback of any error that passed through
this add-on's code (main thread or background thread), then lets Anki handle it as before. No Anki imports."""

import datetime
import os
import sys
import threading
import traceback

DIR = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(DIR, "user_files", "error.log")
MAX_BYTES = 200_000  # past this the file starts over


def _mine(tb, dirs: tuple) -> bool:
    """True if any frame of the traceback is in one of `dirs` (the add-on folder, symlinked or not)."""
    for frame, _line in traceback.walk_tb(tb):
        name = frame.f_code.co_filename
        if any(name.startswith(d + os.sep) for d in dirs):
            return True
    return False


def log_exception(path: str, etype, value, tb, dirs: tuple = (DIR,)) -> bool:
    """Append the error to `path` if it went through the add-on's code; returns whether it did."""
    if not _mine(tb, dirs):
        return False
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        mode = "w" if os.path.exists(path) and os.path.getsize(path) > MAX_BYTES else "a"
        with open(path, mode, encoding="utf-8") as f:
            f.write(f"--- {datetime.datetime.now().isoformat(timespec='seconds')} ---\n")
            f.write("".join(traceback.format_exception(etype, value, tb)) + "\n")
        return True
    except Exception:
        return False  # logging must never cause an error of its own


def install(path: str = PATH):
    """Wrap sys.excepthook and threading.excepthook (call it after Anki has set its own up)."""
    dirs = tuple({DIR, os.path.realpath(DIR)})
    old = sys.excepthook
    old_thread = threading.excepthook

    def hook(etype, value, tb):
        log_exception(path, etype, value, tb, dirs)
        old(etype, value, tb)

    def thread_hook(args):
        log_exception(path, args.exc_type, args.exc_value, args.exc_traceback, dirs)
        old_thread(args)

    sys.excepthook = hook
    threading.excepthook = thread_hook
