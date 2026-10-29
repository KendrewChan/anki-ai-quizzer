import os
import sys
import threading

import pytest

from addon import session
from addon.textutil import parse_json_reply

MODEL = "claude-gpt-6-1-example"
OFFER = "TRAE 排队中：第 100 位（模型繁忙，轮到后自动开始） · 现在可以加速到不用排队（模型不变）：打断后发送「加速」\n"
QUEUED = "TRAE 排队中：第 100 位（模型繁忙，轮到后自动开始）\n"
WAITING = "等待 TRAE 响应中（已等 10 秒，模型响应较慢）\n"


def delta(text):
    return {"type": "stream_event", "event": {"type": "content_block_delta",
            "delta": {"type": "text_delta", "text": text}}}


@pytest.mark.parametrize("events,offered", [
    ([delta(OFFER)], True),
    ([delta(OFFER[:30]), delta(OFFER[30:])], True),
    ([delta(QUEUED), delta(WAITING), delta(OFFER)], True),
    ([delta(OFFER.replace("\n", "\r\n"))], True),
    ([delta(OFFER.replace("不用排队", "第 3 位"))], True),
    ([delta(QUEUED)], False),
    ([delta("Example:\n" + OFFER)], False),
    ([delta("x" * 4097), delta(OFFER)], False),
    ([{"type": "stream_event", "event": {"type": "content_block_delta",
      "delta": {"type": "thinking_delta", "thinking": "working"}}}, delta(OFFER)], False),
    ([{"type": "stream_event", "event": {"type": "content_block_start",
      "content_block": {"type": "tool_use"}}}, delta(OFFER)], False),
    ([dict(delta(OFFER), parent_tool_use_id="agent-1")], False),
    ([{"type": "assistant", "message": {"content": [{"type": "text", "text": OFFER.rstrip()}]}}], True),
    ([delta(QUEUED), {"type": "assistant", "message": {"content": [{"type": "text", "text": "Example:"}]}},
      delta(OFFER)], True),  # full assistant snapshots are not a second copy of streamed text
])
def test_queue_scanner(events, offered):
    scanner = session._FerryQueue()
    assert any(scanner.feed(e) for e in events) is offered


@pytest.mark.parametrize("model,is_ferry", [
    (MODEL, True), ("gpt-6.1-example", True), ("claude-gpt-5-6-example", True),
    ("claude-gpt-6-example", True), ("sonnet", False), ("", False),
])
def test_only_ferry_commands_request_partial_messages(model, is_ferry):
    cmd = session.build_command("/x/claude", model, "S")
    assert ("--include-partial-messages" in cmd) is is_ferry


def call(backend, prompt, timeout=2):
    done, out = threading.Event(), {}
    backend.request(1, prompt, parse_json_reply, timeout,
                    lambda cid, result, err: (out.update(result=result, err=err), done.set()))
    assert done.wait(6), "callback never fired"
    return out


@pytest.mark.parametrize("card_scoped", [True, False])
def test_acceleration_keeps_original_request_and_runs_once(tmp_path, card_scoped):
    fake = [sys.executable, os.path.join(os.path.dirname(__file__), "fake_claude.py"), "--replay-user-messages"]
    backend = session.ClaudeSession(fake, str(tmp_path), lambda fn: fn(), MODEL, card_scoped=card_scoped)
    try:
        result = call(backend, "FERRY_OFFER")
        assert result["err"] is None
        assert result["result"] == {"echo": "FERRY_OFFER", "accelerations": 1}
        assert call(backend, "FERRY_OFFER")["result"]["accelerations"] == 1
    finally:
        backend.close()


@pytest.mark.parametrize("model,prompt", [("sonnet", "FERRY_OFFER"), (MODEL, "FERRY_NO_OFFER")])
def test_no_acceleration_without_matching_model_and_offer(tmp_path, model, prompt):
    fake = [sys.executable, os.path.join(os.path.dirname(__file__), "fake_claude.py"), "--replay-user-messages"]
    backend = session.ClaudeSession(fake, str(tmp_path), lambda fn: fn(), model, card_scoped=True)
    try:
        assert call(backend, prompt, timeout=0.2)["err"].kind == "timeout"
    finally:
        backend.close()


def test_json_repair_does_not_accelerate_a_second_time(tmp_path):
    fake = [sys.executable, os.path.join(os.path.dirname(__file__), "fake_claude.py"), "--replay-user-messages"]
    backend = session.ClaudeSession(fake, str(tmp_path), lambda fn: fn(), MODEL, card_scoped=True)
    try:
        result = call(backend, "FERRY_BADJSON")
        assert result["err"] is None
        assert result["result"] == {"echo": session.RETRY_PROMPT, "n": 3}
    finally:
        backend.close()


def test_ferry_usage_limit_is_not_retried(tmp_path):
    fake = [sys.executable, os.path.join(os.path.dirname(__file__), "fake_claude.py"), "--replay-user-messages"]
    backend = session.ClaudeSession(fake, str(tmp_path), lambda fn: fn(), MODEL, card_scoped=True)
    try:
        assert call(backend, "LIMIT")["err"].kind == "limit"
        assert call(backend, "normal request")["result"]["n"] == 2
    finally:
        backend.close()


def test_explicit_acceleration_request_cannot_loop(tmp_path):
    fake = [sys.executable, os.path.join(os.path.dirname(__file__), "fake_claude.py"), "--replay-user-messages"]
    backend = session.ClaudeSession(fake, str(tmp_path), lambda fn: fn(), MODEL)
    try:
        result = call(backend, "加速")
        assert result["err"] is None and result["result"]["accelerations"] == 1
    finally:
        backend.close()
