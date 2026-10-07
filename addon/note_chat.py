"""The chat's NOTE section: the note open in the reviewer, Browse or Add Cards. No Anki imports."""

from .grading import deck_rules_block, pad
from .textutil import strip_html

MAX_SEARCHES = 3  # Anki searches per chat message
MAX_RESULTS = 20  # notes returned per search
FIELD_CHARS = 300  # per field, plain text

NOTE_RULES = """NOTE: the one Anki note the user has open. They may highlight part of it and ask about it, or ask you to change it. Through "fields" you change only this note — never another one (other cards go through CARDS). The NOTE section says which side of the card the user is on; "Highlighted" in the message is the text they selected — their message is about that text.

QUESTION SIDE (reviewer, before answering): you get only the card's question. Help them understand what is asked (a term, the wording, the scope) without giving away the answer or anything that would let them skip recalling it — even when other context (a deck you read, search results, the web) shows it. Never change the note: "fields" is always {}.

ANSWER SIDE (reviewer after answering, or Browse): you get the note's fields (raw HTML) and, when they were graded, what they were asked and answered and the grade.
- A question: answer it in "reply" — clear and to the point, at most about 120 words unless they ask for more — and change nothing, even if the answer shows a gap in the card (you may suggest adding it).
- A change request: change only what it asks for; keep each field's existing HTML style. "reply" says in one short sentence what you changed.
- Both in one message: do both.
- A field may end with a "Missed (date)" section the add-on maintains — leave it as it is unless the user asks about it. If a change request is unclear, change nothing and ask in "reply".

NEW NOTE (Add Cards): the user is writing a note that isn't saved yet, and you get its fields so far (some may be empty). Rules as on the answer side: answer a question about it (wording, what belongs on the back, splitting it into cards, accuracy) in "reply" and change nothing. When they ask you to write, fill in or change a field, put the whole new field HTML in "fields" and say in one short sentence what you did. Use only the field names you were given. Search their other notes when it helps (is this a duplicate? what style do the existing cards use?).

Key: "fields": {"<field name>": "<the whole new field HTML>", ...} — only the fields you change; {} for none.

Deck rules, when given, take priority over everything else here (including the formatting guide) except the JSON reply format."""


def _fields_block(fields: dict) -> str:
    return "\n\n".join(f"[{name}]\n{value}" for name, value in fields.items())


def answer_side_context(fields: dict, questions: list, answers: list, verdict=None, deck_rules: list = ()) -> str:
    """fields: field name -> raw HTML of the note right now; verdict None = not graded."""
    note = _fields_block(fields)
    review = ""
    if verdict:
        asked = questions or ["(the card's own question)"]
        pairs = "\n".join(f"Q: {q}\nUser: {a.strip() or '(blank)'}" for q, a in zip(asked, pad(answers, len(asked))))
        review = f"\n\nReview:\n{pairs}\nGrade: {verdict.get('verdict')} — {verdict.get('feedback', '')}"
    return f"ANSWER SIDE\n\nNOTE FIELDS\n\n{note}{deck_rules_block(deck_rules)}{review}"


def new_note_context(fields: dict, deck_rules: list = ()) -> str:
    """Add Cards window: the note as typed so far (field name -> HTML)."""
    return f"NEW NOTE\n\nFIELDS SO FAR\n\n{_fields_block(fields) or '(empty)'}{deck_rules_block(deck_rules)}"


def question_side_context(question: str, questions: list, deck_rules: list = ()) -> str:
    """Question side: only what the user can see — never the answer."""
    shown = "".join(f"\n- {q}" for q in questions)
    shown = f"\n\nQuestions shown to the user:{shown}" if shown else ""
    return f"QUESTION SIDE\n\nCard's question:\n{question}{shown}{deck_rules_block(deck_rules)}"


def plan_field_edit(current: dict, proposed: dict) -> tuple:
    """(changes, rejected): changes = fields that exist and actually differ; rejected = unknown field names."""
    changes = {k: v for k, v in proposed.items() if k in current and v != current[k]}
    return changes, [k for k in proposed if k not in current]


def search_block(query: str, notes: list, total: int, last: bool = False, error: str = "") -> str:
    """What a search of the user's collection found, to append to the prompt of the next request.
    notes: [{"deck", "type", "fields": {name: html}}], at most MAX_RESULTS, already limited by the caller."""
    head = f'SEARCH RESULTS for "{query}"'
    if error:
        body = f"The search failed: {error}"
    elif not notes:
        body = "No notes match."
    else:
        shown = f" (first {len(notes)} of {total})" if total > len(notes) else ""
        items = []
        for n in notes:
            fields = "\n".join(f"  {k}: {strip_html(v)[:FIELD_CHARS]}" for k, v in n["fields"].items())
            items.append(f"- Deck: {n['deck']} | Note type: {n['type']}\n{fields}")
        body = f"{total} matching note(s){shown}:\n" + "\n".join(items)
    end = "\nNo more searches: answer now." if last else ""
    return f"\n\n{head}\n{body}{end}"
