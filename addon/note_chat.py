"""Prompts and reply handling for the chats about a note (highlight-to-ask in the reviewer, the Add Cards panel).
No Anki imports."""

from .grading import deck_rules_block, pad
from .textutil import STYLE_GUIDE, parse_json_reply

EDIT_SYSTEM_PROMPT = """You help the user with one Anki note while they review it: they highlight part of the card and ask about it, or ask you to change the note. Never touch any other note. Each message says which side of the card the user is on and, under "Highlighted", the text they selected — their message is about that text.

QUESTION SIDE: they haven't answered yet, and you get only the card's question. Help them understand what is asked (a term, the wording, the scope) without giving away the answer or anything that would let them skip recalling it. Never change the note: "fields" is always {}.

ANSWER SIDE: you get the note's fields (raw HTML) and, when they were graded, what they were asked and answered and the grade.
- A question: answer it in "reply" — clear and to the point, at most about 120 words — and change nothing, even if the answer shows a gap in the card (you may suggest adding it).
- A change request: change only what it asks for; keep each field's existing HTML style. "reply" says in one short sentence what you changed.
- Both in one message: do both.
- A field may end with a "Missed (date)" section the add-on maintains — leave it as it is unless the user asks about it. If a change request is unclear, change nothing and ask in "reply".

NEW NOTE: the user is writing a note that isn't saved yet, and you get its fields so far. Answer their question about it (wording, what belongs on the back, splitting it into cards, accuracy) in "reply", at most about 120 words. Never change anything: "fields" is always {}.

Deck rules, when given, take priority over everything else here (including the formatting guide) except the JSON reply format.

Reply with JSON only, no code fences:
{"reply": "<your answer, or what you changed>", "fields": {"<field name>": "<the whole new field HTML>", ...}}
Include only the fields you change; {} for none.

""" + STYLE_GUIDE


def _highlighted(selection: str) -> str:
    return f"\n\nHighlighted:\n{selection.strip()}" if selection.strip() else ""


def _fields_block(fields: dict) -> str:
    return "\n\n".join(f"[{name}]\n{value}" for name, value in fields.items())


def edit_prompt(fields: dict, request: str, questions: list, answers: list, verdict=None,
                deck_rules: list = (), selection: str = "") -> str:
    """Answer side. fields: field name -> raw HTML of the note right now; verdict None = not graded."""
    note = _fields_block(fields)
    review = ""
    if verdict:
        asked = questions or ["(the card's own question)"]
        pairs = "\n".join(f"Q: {q}\nUser: {a.strip() or '(blank)'}" for q, a in zip(asked, pad(answers, len(asked))))
        review = f"\n\nReview:\n{pairs}\nGrade: {verdict.get('verdict')} — {verdict.get('feedback', '')}"
    return (f"ANSWER SIDE\n\nNOTE FIELDS\n\n{note}{deck_rules_block(deck_rules)}{review}"
            f"{_highlighted(selection)}\n\nUser's request:\n{request}")


def new_note_prompt(fields: dict, request: str, selection: str = "", deck_rules: list = ()) -> str:
    """Add Cards window: the note as typed so far (field name -> HTML)."""
    note = _fields_block(fields) or "(empty)"
    return (f"NEW NOTE\n\nFIELDS SO FAR\n\n{note}{deck_rules_block(deck_rules)}"
            f"{_highlighted(selection)}\n\nUser's request:\n{request}")


def question_side_prompt(question: str, questions: list, request: str, selection: str = "", deck_rules: list = ()) -> str:
    """Question side: only what the user can see — never the answer."""
    shown = "".join(f"\n- {q}" for q in questions)
    shown = f"\n\nQuestions shown to the user:{shown}" if shown else ""
    return (f"QUESTION SIDE\n\nCard's question:\n{question}{shown}{deck_rules_block(deck_rules)}"
            f"{_highlighted(selection)}\n\nUser's request:\n{request}")


def parse_edit_reply(text: str) -> dict:
    obj = parse_json_reply(text)
    fields = obj.get("fields") or {}
    if not isinstance(fields, dict):
        raise ValueError("'fields' is not an object")
    return {"reply": str(obj.get("reply", "")).strip(), "fields": {str(k): str(v) for k, v in fields.items()}}


def plan_field_edit(current: dict, proposed: dict) -> tuple:
    """(changes, rejected): changes = fields that exist and actually differ; rejected = unknown field names."""
    changes = {k: v for k, v in proposed.items() if k in current and v != current[k]}
    return changes, [k for k in proposed if k not in current]
