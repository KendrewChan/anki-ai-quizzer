"""Exercise chat lifecycle methods without importing Qt/Anki or opening a window."""

import ast
from collections import deque
from pathlib import Path
from types import SimpleNamespace

import pytest

from addon import processes


@pytest.fixture
def chat():
    source = Path(__file__).parents[1] / "addon" / "assistant.py"
    classes = [node for node in ast.parse(source.read_text(encoding="utf-8")).body if isinstance(node, ast.ClassDef)]
    replies, pending = [], []
    panel = SimpleNamespace(reply=lambda *args: replies.append(args))
    scope = {"deque": deque, "processes": processes, "_ALL": set(),
             "assistant_ops": SimpleNamespace(HISTORY=3), "ReviewPanel": lambda *args: panel}
    exec(compile(ast.Module(body=classes, type_ignores=[]), str(source), "exec"), scope)
    conversation = scope["Conversation"]("addon", None, lambda sel, done: pending.append(done), "hint")
    conversation._next = lambda: None
    yield conversation, pending, scope["Context"], replies
    conversation.close()
    processes.resume()


@pytest.mark.parametrize("action", ["clear", "close", "profile"])
def test_delayed_context_cannot_resurrect_cleared_or_closed_chat(chat, action):
    conversation, pending, context, replies = chat
    conversation.send(1, "", "question")
    if action == "profile":
        processes.shutdown()
        processes.resume()
    else:
        getattr(conversation, action)()
    pending[0](context("card"))
    assert not conversation.queue and not replies


def test_context_completion_still_queues_an_active_chat(chat):
    conversation, pending, context, replies = chat
    conversation.send(1, "", "question")
    pending[0](context("card"))
    assert len(conversation.queue) == 1 and not replies


def test_closed_chat_cannot_accept_another_message(chat):
    conversation, pending, _, _ = chat
    conversation.close()
    conversation.send(1, "", "too late")
    assert not pending
