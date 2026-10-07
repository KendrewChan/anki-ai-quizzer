"""The study tutor: its system prompt, the ask / grade prompts and parsing their replies. No Anki imports."""

import re

from .textutil import STYLE_GUIDE, parse_json_reply

SYSTEM_PROMPT = """You are a strict flashcard tutor inside Anki. The user studies one card at a time; this whole conversation is one study session.

What the user sees for a card: the card's own question (folded unless you open it), then your questions, each with ONE answer box. A question may have parts, listed under it and answered together in its box. Each question, or each part, can carry a hint shown as a "?" tooltip. It is all one page, read top to bottom, so shared context appears once — never repeat it in every question. The add-on numbers everything — never number anything yourself.

Two kinds of message arrive:

1. NEW CARD — only the card's question (its front), never its answer. Write the questions the user will answer.
   - Ask exactly what the front asks, sharper and more concrete: no extra topics, no answers inside the question. A question that is already concrete stays as it is.
   - One question per distinct point the front bundles — usually one, at most 4 unless deck rules want more (never more than 8). Use parts for sub-points answered together in one box; use separate questions when each needs its own box.
   - When deck rules name the questions or sections to ask, each question is that name exactly as written (e.g. "APIs"), nothing added — put any guidance for it in its hint.
   - hints: a nudge toward the idea that never gives it away — one per question, or for a question with parts, a list with one per part.
   - show_original: true shows the card's own question open above yours — the way to present the card's question as written (then don't repeat it in your questions); false keeps it folded.
   Reply: {"questions": ["<question>" or {"question": "<stem>", "parts": ["<part>", ...]}, ...], "hints": ["<hint>" or ["<hint per part>", ...], ...], "show_original": false}

2. GRADE — the card again (question and reference answer) plus the user's answer to each question asked. Judge only against this card's reference answer, matching each answer to its own question.
   - per_question, in order: the question's verdict, a note, and parts — the user's answer split into its claims, in their own words (filler trimmed, nothing added), each with a verdict and, unless correct, a "why": what is off and what is right. A blank answer is "skipped", not wrong: no parts, and it does not lower the verdict or ease, which judge only the answered questions.
   - verdict (overall): "wrong" (core idea missing or incorrect), "partial" (core idea right, key facts missing), "correct" (all key facts). Verdicts agree upward: a question is no better than its weakest claim, and the card no better than its weakest question.
   - ease: wrong=1, partial=2, correct=3, correct and also complete and crisp=4.
   - feedback: one or two blunt sentences — fix what is wrong, add the most important missing piece. No praise.
   - missed: specific facts from the reference answer the user did not give. [] if none.
   The reference answer may end with a "Missed (date)" section: points the user has missed before, each starting with [N], how many reviews missed it (out of the reviews counted in the header). It is not required content. When the user misses a listed point again, put it in "missed" in that bullet's own words (without the [N]), and say so in feedback.
   Reply: {"per_question": [{"verdict": "wrong"|"partial"|"correct"|"skipped", "note": "...", "parts": [{"text": "...", "verdict": "...", "why": "..."}, ...]}, ...], "verdict": "...", "ease": N, "feedback": "...", "missed": ["..."]}

Keep each hint, note, why and missed item short — about 15 words at most.

A card may come with "Deck rules": instructions for its deck, outermost first, inner winning on conflict, for that card only. Priority: deck rules, then the user's general rules, then everything above. Only the JSON reply format is fixed.

Reply with the JSON object only. No prose, no code fences."""

def system_prompt(custom: list) -> str:
    """Tutor system prompt plus the user's custom rules from the config page."""
    rules = [r for r in (custom or []) if str(r).strip()]
    base = f"{SYSTEM_PROMPT}\n\n{STYLE_GUIDE}"
    if not rules:
        return base
    listed = "\n".join(f"- {r}" for r in rules)
    return f"{base}\n\nUser's general rules (follow them unless they conflict with the JSON reply format; a card's deck rules win over them):\n{listed}"

VERDICTS = ("wrong", "partial", "correct")
SKIPPED = "skipped"  # a question left blank; only per-question marks use it


def split_answer(answer_html: str) -> tuple:
    """(front, back): Anki's rendered answer usually repeats the question above <hr id=answer>. No marker = all back."""
    m = re.search(r"(?i)<hr[^>]*id=[\"']?answer[\"']?[^>]*>", answer_html)
    return (answer_html[:m.end()], answer_html[m.end():]) if m else ("", answer_html)


def answer_only(answer_html: str) -> str:
    return split_answer(answer_html)[1]


def deck_rules_block(deck_rules: list) -> str:
    """deck_rules: [(deck name, prompt)] outermost first."""
    if not deck_rules:
        return ""
    return "\n\nDeck rules (outer → inner):\n" + "\n".join(f"- {name}: {p}" for name, p in deck_rules)


def ask_prompt(question: str, deck_rules: list = (), sharp: bool = True) -> str:
    """Front only: rewritten questions must come from the card's question, never its answer.
    sharp=False: Rewrite question is off for the deck but its deck rules still shape the question side."""
    keep = ("" if sharp else "\n\nRewrite question is off for this deck: the card's question is shown as written above your "
            "questions, so never repeat or rephrase it, and show_original does nothing. Return only what the deck rules ask "
            "for on the question side (e.g. a question per section); if they ask for nothing there, return \"questions\": [].")
    return f"NEW CARD\n\nQuestion:\n{question}{keep}{deck_rules_block(deck_rules)}"


def grade_prompt(question: str, asked: list, answer: str, user_answers: list, deck_rules: list = ()) -> str:
    """asked = questions shown (empty when no rewrite happened: cloze or ask failed)."""
    asked = asked or [question]
    pairs = "\n\n".join(
        f"Q{i}: {q}\nUser's answer {i}: {a.strip() or '(blank)'}"
        for i, (q, a) in enumerate(zip(asked, pad(user_answers, len(asked))), 1)
    )
    return (f"GRADE\n\nCard question:\n{question}\n\nReference answer:\n{answer}"
            f"{deck_rules_block(deck_rules)}\n\n{pairs}")


def pad(items: list, n: int) -> list:
    """Fit the answers to n questions: pad with blanks, fold any extras into the last."""
    items = list(items)
    if len(items) > n:
        items = items[:n - 1] + ["\n".join(items[n - 1:])]
    return items + [""] * (n - len(items))


MAX_QUESTIONS = 8  # the prompt asks for at most 4 unless deck rules want more


def parse_questions(text: str) -> dict:
    """{"questions": [plain text per question, parts as numbered lines — for prompts and the verdict],
        "items": [{"num", "text", "hint", "parts": [{"label", "text", "hint"}]}] — for the question side}.
    Parts are numbered 3.1, 3.2… under question 3 (1., 2. when there is one question); hints sit on the smallest unit."""
    obj = parse_json_reply(text)
    qs = obj.get("questions", obj.get("question"))
    if isinstance(qs, (str, dict)):
        qs = [qs]
    if not isinstance(qs, list):
        raise ValueError("reply has no 'questions'")
    hints = obj.get("hints") if isinstance(obj.get("hints"), list) else []
    raw = []
    for q, h in zip(qs, hints + [None] * len(qs)):
        if isinstance(q, dict):
            parts = q.get("parts") if isinstance(q.get("parts"), list) else []
            stem, parts = str(q.get("question", "")).strip(), [str(p).strip() for p in parts if str(p).strip()]
        else:
            stem, parts = str(q or "").strip(), []
        if stem or parts:
            raw.append((stem, parts, h))
    raw = raw[:MAX_QUESTIONS]
    if not raw:
        raise ValueError("reply has no 'questions'")
    many = len(raw) > 1
    questions, items = [], []
    for i, (stem, parts, h) in enumerate(raw, 1):
        hs = [str(x).strip() for x in h] if isinstance(h, list) else [str(h).strip() if h else ""]
        labels = [f"{i}.{k}" if many else f"{k}." for k in range(1, len(parts) + 1)]
        part_hints = (hs + [""] * len(parts))[:len(parts)]
        items.append({"num": f"{i}." if many else "", "text": stem, "hint": "" if parts else hs[0],
                      "parts": [{"label": lb, "text": p, "hint": ph} for lb, p, ph in zip(labels, parts, part_hints)]})
        questions.append("\n".join([stem] + [f"{lb} {p}" for lb, p in zip(labels, parts)]).strip())
    return {"questions": questions, "items": items, "show_original": obj.get("show_original") is True}


def parse_added_questions(text: str) -> dict:
    """Rewrite question off: questions the deck rules add under the card's own question; none is fine (one plain box)."""
    try:
        return parse_questions(text)
    except ValueError:
        parse_json_reply(text)  # still fail on a reply that isn't JSON at all
        return {"questions": [], "items": [], "show_original": False}


def parse_grade(text: str) -> dict:
    obj = parse_json_reply(text)
    verdict = str(obj.get("verdict", "")).lower()
    if verdict not in VERDICTS:
        raise ValueError(f"bad verdict: {verdict!r}")
    try:
        ease = min(4, max(1, int(obj.get("ease"))))
    except (TypeError, ValueError):
        ease = {"wrong": 1, "partial": 2, "correct": 3}[verdict]
    missed = obj.get("missed") or []
    if not isinstance(missed, list):
        missed = [missed]
    per_question = []
    for pq in obj.get("per_question") or []:
        if isinstance(pq, dict):
            v = str(pq.get("verdict", "")).lower()
            parts = pq.get("parts") if isinstance(pq.get("parts"), list) else []
            parts = [{"text": str(x.get("text", "")).strip(), "verdict": str(x.get("verdict", "")).lower(),
                      "why": str(x.get("why") or "").strip()} for x in parts if isinstance(x, dict)]
            per_question.append({"verdict": v if v in VERDICTS + (SKIPPED,) else "partial", "note": str(pq.get("note", "")).strip(),
                                 "parts": [x for x in parts if x["text"] and x["verdict"] in VERDICTS]})
    return {
        "per_question": per_question,
        "verdict": verdict,
        "ease": ease,
        "feedback": str(obj.get("feedback", "")).strip(),
        "missed": [str(m).strip() for m in missed if str(m).strip()],
    }
