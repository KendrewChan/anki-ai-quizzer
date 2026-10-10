#!/usr/bin/env python3
"""Stand-in for `claude -p --input-format stream-json --output-format stream-json`.

Per user message (keywords in the content): SLEEP:<s> delays, CRASH exits, BADJSON replies
with prose, ERROR / LIMIT reply with is_error. Otherwise replies {"echo": content, "n": turn}.
A stream-json interrupt (control_request) cuts a SLEEP short and ends that turn with an error result, as the real CLI.
BACKGROUND: like a background subagent, once the reply is out the CLI starts a turn by itself, with its own result.
With --replay-user-messages each message is echoed back (with its uuid) when its turn starts, as the real CLI.
"""

import json
import queue
import re
import sys
import threading

sys.stdin.reconfigure(encoding="utf-8")  # like the real CLIs: raw UTF-8 both ways, on every OS
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")


def emit(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


REPLAY = "--replay-user-messages" in sys.argv
NOTIFICATION = object()  # the turn a finished background subagent starts
emit({"type": "system", "subtype": "init", "tools": [], "model": "fake-claude-model"})
messages = queue.Queue()
interrupted = threading.Event()


def read():
    for line in sys.stdin:
        obj = json.loads(line)
        if obj.get("type") == "control_request":
            interrupted.set()
            emit({"type": "control_response", "response": {"subtype": "success", "request_id": obj["request_id"]}})
        else:
            messages.put(obj)
    messages.put(None)


threading.Thread(target=read, daemon=True).start()
turn = 0
while True:
    obj = messages.get()
    if obj is None:
        break
    turn += 1
    if obj is NOTIFICATION:
        text = "```json\n" + json.dumps({"echo": "background agent finished", "n": turn}) + "\n```"
        emit({"type": "result", "subtype": "success", "is_error": False, "result": text})
        continue
    content = obj["message"]["content"]
    if REPLAY:
        emit({"type": "user", "message": obj["message"], "uuid": obj.get("uuid"), "isReplay": True})
    interrupted.clear()
    m = re.search(r"SLEEP:([\d.]+)", content)
    if m and interrupted.wait(float(m.group(1))):
        emit({"type": "result", "subtype": "error_during_execution", "is_error": True, "result": ""})
        continue
    if "CRASH" in content:
        sys.stderr.write("boom\n")
        sys.exit(1)
    if "ERROR" in content or "LIMIT" in content:
        msg = "Claude AI usage limit reached" if "LIMIT" in content else "Invalid API key"
        emit({"type": "result", "subtype": "success", "is_error": True, "result": msg})
        continue
    text = "sure, here you go" if "BADJSON" in content else "```json\n" + json.dumps({"echo": content, "n": turn}) + "\n```"
    if "BACKGROUND" in content:  # queued ahead of any message sent after this reply, as the real CLI runs it first
        messages.put(NOTIFICATION)
    emit({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}})
    emit({"type": "result", "subtype": "success", "is_error": False, "result": text})
