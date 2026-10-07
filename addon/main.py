"""Anki wiring: reviewer hooks, pycmd bridge, side-panel chats, Missed append, main-page toggle + AI Window link."""

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

from . import assistant, config_ops, errorlog, grading, health, missed, note_chat, state, ui
from .ai_window import AIWindow
from .assistant import Context, Conversation
from .tab_page import deck_ids, load_config, migrate_once
from .session import make_backend, provider_of
from .side_panel import ADD_HINT, BROWSE_HINT, ReviewPanel, SelectionBubble
from .textutil import strip_html

ADDON = __name__.split(".")[0]


class State:
    def __init__(self):
        self.enabled = bool(state.get("ui", "ai_study"))  # AI Study mode; as the user last left it
        self.session = None
        self.cwd = None
        self.window = None  # ai_window.AIWindow
        self.bypass = False  # reveal() is showing the answer: don't intercept it
        self.chat = None  # assistant.Conversation: the reviewer's highlight-to-ask chat
        self.panel = None  # its side_panel.ReviewPanel
        self.action = None
        self.window_action = None
        self.reset()

    def reset(self):
        """Per review session."""
        self.card_id = None
        self.ctx = {}  # card_id -> {"q", "a", "questions"}
        self.verdicts = {}  # card_id -> (verdict, questions, answers)
        self.key_reveal = False  # Space/Enter was just pressed: the coming _showAnswer must not grade
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


def around_enter_key(reviewer, *args, _old):
    """Space/Enter pressed in the reviewer: remember it, so the answer is shown without grading."""
    S.key_reveal = reviewer.state == "question"
    return _old(reviewer, *args)


def around_show_answer(reviewer, *args, _old):
    """Anki's Show Answer button grades what is typed, but only if any box has text; otherwise it just shows the answer.
    Space/Enter (around_enter_key) never grade, so a stray key can't start a grading. Anything else keeps Anki's behaviour."""
    card = reviewer.card
    key, S.key_reveal = S.key_reveal, False
    if (S.bypass or key or reviewer.state != "question" or card is None or card.id in S.no_grade
            or card.id not in S.ctx or not active(card)):
        return _old(reviewer, *args)

    def on_page(result):
        if result == "none":  # nothing typed (or no boxes yet): just show the answer
            reveal()

    reviewer.web.evalWithCallback("window.aiStudy ? aiStudy.submitNow() : 'none'", on_page)


def on_show_question(card):
    S.key_reveal = False
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
    past = []
    if grading.wants_missed(rules):
        note = card.note()
        field = missed.pick_missed_field(list(note.keys()))
        past = [(strip_html(h), n) for h, n in missed.parse_missed(note[field] if field else "")[1]]
    session().request(card.id, grading.ask_prompt(q, rules, sharp=mode == "sharp", missed=past), parse,
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
        elif message == "aiStudy:window":
            S.window.open()
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


def guarded(done, build):
    """Call build() -> Context and hand it to done; errors go to the panel (they'd vanish in a Qt callback)."""
    try:
        done(build())
    except Exception as e:
        done(f"Failed: {type(e).__name__}: {e}")


def reviewer_context(_sel: str, done):
    """Highlight-to-ask, about the card on screen. Question side: help without the answer, never edits. Answer side:
    the note can be changed (one undo step)."""
    card = mw.reviewer.card if mw.state == "review" and mw.reviewer else None
    if card is None or not active(card):
        done("Open a card with AI Study on to ask about it.")
        return
    rules, deck = deck_rules(card, cfg()), home_deck(card)
    if mw.reviewer.state == "question":
        ctx = S.ctx.get(card.id) or {}
        note = note_chat.question_side_context(ctx.get("q") or strip_html(card.question()), ctx.get("questions", []),
                                               rules)
        done(Context(f"the reviewer, question side of a card in {deck}", ["note"], note, deck=deck))
        return
    verdict, questions, answers = S.verdicts.get(card.id, (None, [], []))
    n = card.note()
    nid = n.id
    note = note_chat.answer_side_context(dict(n.items()), questions, answers, verdict, rules)
    done(Context(f"the reviewer, answer side of a card in {deck}", ["note"], note,
                 lambda fields, reply, say: apply_note_edit(nid, fields, reply, say, mw.reviewer,
                                                            lambda: redraw_edited(nid)), deck=deck))


def redraw_edited(nid: int):
    """Show the reviewer's card with the AI's edit, keeping the keyboard in the chat box. Anki's own redraw focuses the
    card, so the next keys typed for the chat would hit reviewer shortcuts (Space/Enter grade, E opens the editor), and
    an edit that adds a card (a new cloze, Add Reverse) would make it jump to the next card."""
    r = mw.reviewer
    if mw.state != "review" or r.card is None or r.card.nid != nid:
        return  # moved on meanwhile: the next card shows the edit anyway
    typing = S.panel.has_focus()
    r._redraw_current_card()
    if typing:
        S.panel.chat.focus()


def apply_note_edit(nid: int, fields: dict, reply: str, say, initiator=None, on_saved=None):
    """Write the field changes the AI asked for, as one undo step, and report through say(text, err). With no
    initiator every screen redraws itself; the reviewer passes itself and redraws in `on_saved`."""
    note = mw.col.get_note(nid)  # fresh: the Missed append or the editor may have saved in the meantime
    changes, unknown = note_chat.plan_field_edit(dict(note.items()), fields)
    reply = reply or ("Done." if changes else "No change.")
    if unknown:
        reply += f" (ignored unknown fields: {', '.join(unknown)})"
    if not changes:
        say(reply, bool(unknown))
        return
    for name, value in changes.items():
        note[name] = value
    done = f"{reply} Changed: {', '.join(changes)} — Edit → Undo reverts it."

    def saved(_):
        say(done, False)
        if on_saved:
            on_saved()

    (
        update_note(parent=mw, note=note)
        .success(saved)
        .failure(lambda e: say(f"Not saved: {e}", True))
        .run_in_background(initiator=initiator)
    )


def on_browser_will_show(browser):
    """Browse window: select text in the note editor and click the "AI" bubble (or use the AI Study menu) to chat
    about the selected note, which the AI may edit (only while AI Study is on)."""
    if not S.enabled:
        return
    chat = Conversation(ADDON, S.window, lambda sel, done: browse_context(browser, done), BROWSE_HINT, browser)
    bubble = SelectionBubble(browser.editor.web, chat.panel.show_selection)
    menu = browser.form.menubar.addMenu("AI Study")
    action = menu.addAction("Chat about this note")
    action.triggered.connect(lambda: chat.panel.toggle() if S.enabled else None)
    browser._ai_chat = chat  # keep them alive with the window
    browser._ai_bubble = bubble
    browser.destroyed.connect(lambda *_: chat.close())  # stop its CLI


def browse_context(browser, done):
    """The note open in the Browse editor; answered and edited like the reviewer's answer side."""
    if not S.enabled or S.disabled:
        done("AI Study is off.")
        return

    def build():
        note = browser.editor.note
        if note is None:
            return "Select a single note first."
        note = mw.col.get_note(note.id)  # as just saved
        card = browser.card
        if card is not None and not active(card):
            return "AI Study is off for this deck."
        rules = deck_rules(card, cfg()) if card is not None else []
        deck = home_deck(card) if card is not None else None
        nid = note.id
        return Context(f"the Browse window, editing a note{f' in {deck}' if deck else ''}", ["note"],
                       note_chat.answer_side_context(dict(note.items()), [], [], None, rules),
                       lambda fields, reply, say: apply_note_edit(nid, fields, reply, say), deck=deck)

    browser.editor.call_after_note_saved(lambda *_: guarded(done, build))


def on_add_cards_init(addcards):
    """An "AI Study" button in the Add Cards window opens/closes a chat panel at its side (only while AI Study is on)."""
    if not S.enabled:
        return
    chat = Conversation(ADDON, S.window, lambda sel, done: add_cards_context(addcards, done), ADD_HINT, addcards)
    button = addcards.form.buttonBox.addButton("AI Study", QDialogButtonBox.ButtonRole.ActionRole)
    button.setAutoDefault(False)  # Enter in the editor must not press it
    button.clicked.connect(lambda: chat.panel.toggle() if S.enabled else None)
    addcards._ai_chat = chat  # keep it alive with the window
    addcards.destroyed.connect(lambda *_: chat.close())  # stop its CLI


def add_cards_context(addcards, done):
    """The note being written in the Add Cards window. The AI may fill in or change its fields (in the editor only:
    the note isn't saved until the user adds it)."""
    if not S.enabled or S.disabled:
        done("AI Study is off.")
        return

    def build():
        note = addcards.editor.note
        deck = mw.col.decks.name(addcards.deck_chooser.selected_deck_id)
        rules = config_ops.deck_chain(deck, deck_ids(), cfg().get("deck_prompts") or {})
        return Context(f"the Add Cards window, writing a new note for {deck}", ["note"],
                       note_chat.new_note_context(dict(note.items()) if note else {}, rules),
                       lambda fields, reply, say: apply_new_note_edit(addcards, fields, reply, say), deck=deck)

    addcards.editor.call_after_note_saved(lambda *_: guarded(done, build))  # the field being typed in counts too


def apply_new_note_edit(addcards, fields: dict, reply: str, say):
    """Put the field changes the AI asked for into the Add Cards editor; report through say(text, err)."""
    note = addcards.editor.note  # the live editor note: the user may have typed since the request
    if note is None:
        say("The note is gone.", True)
        return
    changes, unknown = note_chat.plan_field_edit(dict(note.items()), fields)
    reply = reply or ("Done." if changes else "No change.")
    if unknown:
        reply += f" (ignored unknown fields: {', '.join(unknown)})"
    if changes:
        for name, value in changes.items():
            note[name] = value
        addcards.editor.loadNote()
        reply += f" Changed: {', '.join(changes)}."
    say(reply, bool(unknown) and not changes)


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
    """Leaving the reviewer or closing the profile: kill the grading process; the next session rebuilds it from config.
    The chat panel closes; its conversation stays until Clear or the profile closes."""
    if S.session is not None:
        S.session.close()
        S.session = None
    if S.panel is not None:
        S.panel.close()
    S.reset()


def on_config_changed():
    """Settings changed (maybe from a chat in the middle of a review): the next AI call starts a CLI with them, and AI
    turned off by failures gets another try. The card on screen keeps its questions and grade."""
    if S.session is not None:
        S.session.close()
        S.session = None
    S.failures, S.disabled = 0, None


def on_profile_close():
    end_session()
    S.window.close()
    assistant.close_all()


# --- toggle + AI Window link ---

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
        '<a href=# onclick="pycmd(\'aiStudy:window\');return false;">🤖 AI Window</a></div>'
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
    S.window_action = QAction("AI Window", mw)
    S.window_action.triggered.connect(lambda: S.window.open())
    mw.form.menuTools.addAction(S.window_action)


def on_sync_finished():
    """Synced settings are read from the collection on use; only an open Settings tab needs redrawing."""
    migrate_once(ADDON, after_sync=True)
    S.window.settings.refresh()


def setup():
    errorlog.install()  # tracebacks from this add-on also go to user_files/error.log
    S.window = AIWindow(ADDON, on_config_changed)
    S.chat = Conversation(ADDON, S.window, reviewer_context, ReviewPanel.HINT)
    S.panel = S.chat.panel
    setup_menu()
    gui_hooks.deck_browser_will_render_content.append(on_deck_browser)
    gui_hooks.overview_will_render_content.append(on_overview)
    Reviewer.onEnterKey = wrap(Reviewer.onEnterKey, around_enter_key, "around")
    Reviewer._showAnswer = wrap(Reviewer._showAnswer, around_show_answer, "around")
    gui_hooks.add_cards_did_init.append(on_add_cards_init)
    gui_hooks.browser_will_show.append(on_browser_will_show)
    gui_hooks.card_will_show.append(on_card_will_show)
    gui_hooks.reviewer_did_show_question.append(on_show_question)
    gui_hooks.reviewer_did_show_answer.append(on_show_answer)
    gui_hooks.webview_did_receive_js_message.append(on_js_message)
    gui_hooks.reviewer_will_end.append(end_session)
    gui_hooks.profile_will_close.append(on_profile_close)
    gui_hooks.sync_did_finish.append(on_sync_finished)
