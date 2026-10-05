"""Anki wiring: reviewer hooks, pycmd bridge, side-panel chats, Missed append, main-page toggle + settings link."""

import datetime
import json
import tempfile

from anki.consts import MODEL_CLOZE
from anki.hooks import wrap
from aqt import gui_hooks, mw
from aqt.deckbrowser import DeckBrowser
from aqt.operations.note import update_note
from aqt.overview import Overview
from aqt.qt import QAction, QDialogButtonBox
from aqt.reviewer import Reviewer

from . import config_ops, grading, health, missed, note_chat, state, ui
from .chat_page import deck_ids, load_config, migrate_once
from .config_page import ConfigPage
from .generate_page import GeneratePage
from .missed_page import MissedPage
from .session import make_backend, provider_of
from .side_panel import AddPanel, ReviewPanel
from .textutil import strip_html

ADDON = __name__.split(".")[0]


class State:
    def __init__(self):
        self.enabled = bool(state.get("ui", "ai_study"))  # AI Study mode; as the user last left it
        self.session = None
        self.edit_session = None  # separate CLI for highlight questions / note changes
        self.cwd = None
        self.page = None
        self.gen_page = None
        self.missed_page = None
        self.bypass = False  # reveal() is showing the answer: don't intercept it
        self.panel = None  # side_panel.ReviewPanel: the highlight-to-ask chat
        self.action = None
        self.reset()

    def reset(self):
        """Per review session."""
        self.card_id = None
        self.ctx = {}  # card_id -> {"q", "a", "questions"}
        self.verdicts = {}  # card_id -> (verdict, questions, answers)
        self.no_grade = set()  # card ids whose grading failed: Space shows the answer instead of retrying
        self.failures = 0
        self.disabled = None  # reason string once AI is off for this session


S = State()


def cfg() -> dict:
    return load_config(ADDON)


def session():
    if S.session is None:
        c = cfg()
        S.cwd = S.cwd or tempfile.mkdtemp(prefix="anki_ai_")
        S.session = make_backend(c, grading.system_prompt(c.get("custom")), S.cwd, mw.taskman.run_on_main)
    return S.session


def edit_session():
    if S.edit_session is None:
        S.cwd = S.cwd or tempfile.mkdtemp(prefix="anki_ai_")
        S.edit_session = make_backend(cfg(), note_chat.EDIT_SYSTEM_PROMPT, S.cwd, mw.taskman.run_on_main)
    return S.edit_session


def active(card=None) -> bool:
    """AI Study on (and not disabled by failures) — and, given a card, on for its home deck."""
    if not (S.enabled and not S.disabled):
        return False
    return card is None or config_ops.deck_toggle_on(cfg(), "ai", home_deck(card), deck_ids())


def home_deck(card) -> str:
    """The card's own deck name (its home deck when it sits in a filtered deck)."""
    return mw.col.decks.name(card.odid or card.did)


def deck_rules(card, c: dict) -> list:
    """Prompt chain for the card's own deck."""
    return config_ops.deck_chain(home_deck(card), deck_ids(), c.get("deck_prompts") or {})


def rewrite_enabled(card) -> str:
    """Question step: "sharp", "keep" (Rewrite question off but a deck prompt applies) or "" (none; always for cloze)."""
    if card.note_type()["type"] == MODEL_CLOZE:
        return ""
    return config_ops.ask_mode(cfg(), home_deck(card), deck_ids())


def eval_card(js: str):
    if mw.reviewer and mw.reviewer.web:
        mw.reviewer.web.eval(js)


def on_error(err) -> str:
    """Apply the failure policy; return the message to show. Settings diagnoses the last error on open."""
    health.LAST_ERROR[provider_of(cfg())] = err.message
    S.failures, S.disabled, text = health.study_failure(err.kind, err.message, S.failures, S.disabled)
    return text


# --- hooks ---

def on_card_will_show(text: str, card, kind: str) -> str:
    if kind == "reviewQuestion" and active(card):
        return ui.question_html(text, rewrite_enabled(card)) + ui.ask_html()
    if kind != "reviewAnswer":
        return text
    if card.id in S.verdicts:
        # Below the front: Anki scrolls <hr id=answer> to the top, so anything above it starts off-screen.
        front, back = grading.split_answer(text)
        text = front + ui.verdict_html(*S.verdicts[card.id]) + back
    return text + ui.ask_html() if active(card) else text


def reveal():
    """Show the answer without grading."""
    S.bypass = True
    try:
        mw.reviewer._showAnswer()
    finally:
        S.bypass = False


def around_show_answer(reviewer, *args, _old):
    """Anki's Space and Show Answer: with AI Study on for the card they grade what is typed, but only if any box has
    text; otherwise they just show the answer. Anything else keeps Anki's behaviour."""
    card = reviewer.card
    if (S.bypass or reviewer.state != "question" or card is None or card.id in S.no_grade
            or card.id not in S.ctx or not active(card)):
        return _old(reviewer, *args)

    def on_page(result):
        if result == "none":  # nothing typed (or no boxes yet): just show the answer
            reveal()

    reviewer.web.evalWithCallback("window.aiStudy ? aiStudy.submitNow() : 'none'", on_page)


def on_show_question(card):
    S.card_id = card.id
    S.no_grade.discard(card.id)
    S.verdicts.pop(card.id, None)
    if not active(card):
        return
    q = strip_html(card.question())
    a = strip_html(grading.answer_only(card.answer()))
    c = cfg()
    rules = deck_rules(card, c)
    S.ctx[card.id] = {"q": q, "a": a, "questions": [], "rules": rules}
    mode = rewrite_enabled(card)
    if not mode:
        return
    parse = grading.parse_questions if mode == "sharp" else grading.parse_added_questions
    session().request(card.id, grading.ask_prompt(q, rules, sharp=mode == "sharp"), parse,
                      c.get("ask_timeout_s", 30), on_asked)


def on_asked(card_id, result, err):
    if card_id != S.card_id or mw.reviewer.state != "question":
        return
    if err:
        eval_card(ui.js_call("askFailed", on_error(err)))
        return
    S.failures = 0
    S.ctx[card_id]["questions"] = result["questions"]
    eval_card(ui.js_call("setQuestions", ui.display_items(result["items"]), result["show_original"]))


def on_js_message(handled, message: str, context):
    if not message.startswith("aiStudy:"):
        return handled
    if isinstance(context, (DeckBrowser, Overview)):
        if message == "aiStudy:toggle":
            set_enabled(not S.enabled)
        elif message == "aiStudy:settings":
            S.page.open()
        elif message == "aiStudy:generate":
            S.gen_page.open()
        elif message == "aiStudy:missed":
            S.missed_page.open()
        return (True, None)
    if not isinstance(context, Reviewer):
        return handled
    if message == "aiStudy:reveal":
        if mw.reviewer.state == "question":
            reveal()
    elif message.startswith("aiStudy:submit:"):
        submit(message[len("aiStudy:submit:"):])
    elif message.startswith("aiStudy:open:"):
        S.panel.show_selection(message[len("aiStudy:open:"):])
    return (True, None)


def submit(payload: str):
    card_id = S.card_id
    ctx = S.ctx.get(card_id)
    if ctx is None or not active():
        reveal()
        return
    answers = [str(a) for a in json.loads(payload)]
    questions = list(ctx["questions"])  # snapshot: what the user saw when submitting
    prompt = grading.grade_prompt(ctx["q"], questions, ctx["a"], answers, ctx["rules"])

    def on_graded(cid, result, err):
        if cid != S.card_id or mw.reviewer.state != "question":
            return
        if err:
            S.no_grade.add(cid)
            eval_card(ui.js_call("gradeFailed", on_error(err)))
            return
        S.failures = 0
        S.verdicts[cid] = (result, questions, answers)
        reveal()
        append_missed(result["missed"])

    session().request(card_id, prompt, grading.parse_grade, cfg().get("grade_timeout_s", 60), on_graded)


def reply_only(panel):
    """Callback for chats that only answer: any "fields" in the reply are ignored."""
    def on_reply(_cid, result, err):
        panel.reply(f"Failed: {err.message}" if err else result["reply"] or "…", bool(err))
    return on_reply


def ask(sel: str, request: str):
    """Highlight-to-ask from the side panel, about the card on screen. Question side: help without the answer, never
    edits. Answer side: answer questions and change the note when asked (one undo step). Replies go to the panel."""
    card = mw.reviewer.card if mw.state == "review" and mw.reviewer else None
    if card is None or not request or not active(card):
        S.panel.reply("Open a card with AI Study on to ask about it.", True)
        return
    if mw.reviewer.state == "question":
        ask_question_side(card, sel, request)
    else:
        ask_answer_side(card, sel, request)


def ask_question_side(card, sel: str, request: str):
    ctx = S.ctx.get(card.id) or {}
    prompt = note_chat.question_side_prompt(ctx.get("q") or strip_html(card.question()),
                                            ctx.get("questions", []), request, sel, deck_rules(card, cfg()))
    edit_session().request(card.id, prompt, note_chat.parse_edit_reply, cfg().get("grade_timeout_s", 60),
                           reply_only(S.panel))


def ask_answer_side(card, sel: str, request: str):
    cid, c = card.id, cfg()
    verdict, questions, answers = S.verdicts.get(cid, (None, [], []))
    note = card.note()
    nid = note.id
    prompt = note_chat.edit_prompt(dict(note.items()), request, questions, answers, verdict, deck_rules(card, c), sel)

    def on_edited(_cid, result, err):
        if err:
            S.panel.reply(f"Failed: {err.message}", True)  # not counted toward disabling AI Study
            return
        note = mw.col.get_note(nid)  # fresh: the Missed append may have saved in the meantime
        changes, unknown = note_chat.plan_field_edit(dict(note.items()), result["fields"])
        reply = result["reply"] or ("Done." if changes else "No change.")
        if unknown:
            reply += f" (ignored unknown fields: {', '.join(unknown)})"
        if not changes:
            S.panel.reply(reply, bool(unknown))
            return
        for name, value in changes.items():
            note[name] = value
        done = f"{reply} Changed: {', '.join(changes)} — Edit → Undo reverts it."
        (
            # No initiator: the reviewer sees a note change and redraws the card with the new text.
            update_note(parent=mw, note=note)
            .success(lambda _: S.panel.reply(done))
            .failure(lambda e: S.panel.reply(f"Not saved: {e}", True))
            .run_in_background()
        )

    edit_session().request(cid, prompt, note_chat.parse_edit_reply, c.get("grade_timeout_s", 60), on_edited)


def on_add_cards_init(addcards):
    """An "AI Study" button in the Add Cards window opens/closes a chat panel at its side (only while AI Study is on)."""
    if not S.enabled:
        return
    panel = AddPanel(addcards, lambda sel, text: ask_new(addcards, panel, sel, text))
    button = addcards.form.buttonBox.addButton("AI Study", QDialogButtonBox.ButtonRole.ActionRole)
    button.setAutoDefault(False)  # Enter in the editor must not press it
    button.clicked.connect(lambda: panel.toggle() if S.enabled else None)
    addcards._ai_panel = panel  # keep it alive with the window


def ask_new(addcards, panel, sel: str, request: str):
    """A question about the note being written in the Add Cards window. Answers only; nothing is ever written."""
    if not request or not S.enabled or S.disabled:
        panel.reply("AI Study is off.", True)
        return

    def go(*_):
        try:
            send()
        except Exception as e:  # runs in a Qt callback, where errors would vanish and leave the panel on "Thinking…"
            panel.reply(f"Failed: {type(e).__name__}: {e}", True)

    def send():
        note = addcards.editor.note
        c = cfg()
        did = addcards.deck_chooser.selected_deck_id
        rules = config_ops.deck_chain(mw.col.decks.name(did), deck_ids(), c.get("deck_prompts") or {})
        prompt = note_chat.new_note_prompt(dict(note.items()) if note else {}, request, sel, rules)
        edit_session().request(0, prompt, note_chat.parse_edit_reply, c.get("grade_timeout_s", 60), reply_only(panel))

    addcards.editor.call_after_note_saved(go)  # the field being typed in counts too


def append_missed(bullets: list):
    """Replace the card's Missed section with this review's misses (or "nothing") + today's date."""
    if not config_ops.toggle_on(cfg(), "missed_append"):
        return
    note = mw.reviewer.card.note()
    field = missed.pick_missed_field(list(note.keys()))
    if field is None:
        return
    note[field] = missed.replace_missed(note[field], bullets, datetime.date.today().isoformat())
    (
        update_note(parent=mw, note=note)
        .failure(lambda e: eval_card(ui.append_verdict_note_js(f"Missed notes not saved: {e}")))
        .run_in_background(initiator=mw.reviewer)
    )


def on_show_answer(card):
    if card.id in S.verdicts:
        ease = S.verdicts[card.id][0]["ease"]
        mw.reviewer.bottom.web.eval(f"setTimeout(function(){{ {ui.outline_button_js(ease)} }}, 50);")


def end_session(*_args):
    """Leaving the reviewer or closing the profile: kill the process; the next session rebuilds it from config."""
    for name in ("session", "edit_session"):
        if getattr(S, name) is not None:
            getattr(S, name).close()
            setattr(S, name, None)
    if S.panel is not None:
        S.panel.reset()
    S.reset()


# --- toggle + settings link ---

def set_enabled(on: bool):
    S.enabled = on
    state.put("ui", "ai_study", on)
    if not on:
        end_session()
    if S.action is not None:
        S.action.setChecked(on)
    if mw.state == "deckBrowser":
        mw.deckBrowser.refresh()
    elif mw.state == "overview":
        mw.overview.refresh()


def controls_html() -> str:
    on = "ON" if S.enabled else "OFF"
    color = "#27864a" if S.enabled else "#888"
    return (
        '<div style="margin:1em auto;text-align:center;font-size:0.95em">'
        f'<a href=# onclick="pycmd(\'aiStudy:toggle\');return false;" style="text-decoration:none">'
        f'AI Study: <b style="color:{color}">{on}</b></a>'
        ' &nbsp;·&nbsp; '
        '<a href=# onclick="pycmd(\'aiStudy:settings\');return false;">⚙ Settings</a>'
        ' &nbsp;·&nbsp; '
        '<a href=# onclick="pycmd(\'aiStudy:generate\');return false;">✨ Generate/Update Cards</a>'
        ' &nbsp;·&nbsp; '
        '<a href=# onclick="pycmd(\'aiStudy:missed\');return false;">📋 Today\'s Missed</a></div>'
    )


def on_deck_browser(_browser, content):
    content.stats += controls_html()


def on_overview(_overview, content):
    content.table += controls_html()  # right under "Study Now"


def setup_menu():
    S.action = QAction("AI Study mode", mw)
    S.action.setCheckable(True)
    S.action.setChecked(S.enabled)
    S.action.toggled.connect(lambda on: on != S.enabled and set_enabled(on))
    mw.form.menuTools.addAction(S.action)


def on_sync_finished():
    """Synced settings are read from the collection on use; only an open Settings page needs redrawing."""
    migrate_once(ADDON, after_sync=True)
    if S.page and mw.state == S.page.STATE:
        S.page.refresh()


def setup():
    S.page = ConfigPage(ADDON, end_session)
    S.panel = ReviewPanel(ask)
    S.gen_page = GeneratePage(ADDON)
    S.missed_page = MissedPage(ADDON)
    setup_menu()
    gui_hooks.deck_browser_will_render_content.append(on_deck_browser)
    gui_hooks.overview_will_render_content.append(on_overview)
    Reviewer._showAnswer = wrap(Reviewer._showAnswer, around_show_answer, "around")
    gui_hooks.add_cards_did_init.append(on_add_cards_init)
    gui_hooks.card_will_show.append(on_card_will_show)
    gui_hooks.reviewer_did_show_question.append(on_show_question)
    gui_hooks.reviewer_did_show_answer.append(on_show_answer)
    gui_hooks.webview_did_receive_js_message.append(on_js_message)
    gui_hooks.reviewer_will_end.append(end_session)
    gui_hooks.profile_will_close.append(end_session)
    gui_hooks.sync_did_finish.append(on_sync_finished)
