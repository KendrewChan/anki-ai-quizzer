"""✨ Generate/Update: the AI Window's tab for cards the chat staged in "AI-GEN" — review, approve, Submit — and the
Desktop reference files the chat makes cards from. The card requests themselves run in assistant.py."""

import html
import json
from collections import deque

from aqt import mw
from aqt.operations import CollectionOp
from aqt.qt import QFileDialog

from . import generate_col, generate_ops
from .tab_page import Tab
from .config_page import CSS as CONFIG_CSS
from .textutil import safe_html, strip_html

TEMP = html.escape(generate_ops.TEMP_DECK)

CSS = CONFIG_CSS + """
<style>
#cfg { max-width: min(96vw, 120em); margin: 0.5em auto; padding: 0 0.8em; }  /* cards need room: wider and tighter than Settings */
#refrow { display: flex; gap: 0.4em; align-items: center; margin: 0.6em 0 0.2em; }
#ref { flex: 1; padding: 0.45em 0.6em; font: inherit; border-radius: 6px; border: 1px dashed #8888;
       background: transparent; color: inherit; cursor: default; outline: none; }
#refinfo { font-size: 0.85em; opacity: 0.75; min-height: 1.2em; margin-bottom: 0.5em; }
#refinfo.bad { color: #d33; opacity: 1; }
.stg .deck { font-weight: 600; margin: 0.8em 0 0.2em; display: flex; justify-content: space-between; }
.stg .deck button { font-weight: normal; }
.stg .card { display: flex; gap: 0.6em; align-items: flex-start; margin: 0.15em 0 0.15em 1em; }
.stg .main { flex: 1; min-width: 0; } .stg .q { white-space: pre-wrap; overflow-wrap: anywhere; }
.stg .plain { padding-left: 1.05em; } .stg .acts { white-space: nowrap; }
.stg .acts button { font-size: 0.8em; margin-left: 0.3em; }
.stg .card.ok .q { opacity: 0.75; }
.stg .card .v-orig, .stg .card.orig .v-upd, .stg .card .l-orig, .stg .card.orig .l-upd { display: none; }
.stg .card.orig .v-orig, .stg .card.orig .l-orig { display: inline; } .stg .card.orig .v-orig { display: block; } .stg .okmark { color: #27864a; font-size: 0.8em; font-weight: 600; }
.stg .btns .submit { font-weight: 700; margin-left: 1em; } .stg .hint { font-size: 0.8em; opacity: 0.6; margin-top: 0.3em; }
#status.busy { opacity: 1; font-size: 0.95em; color: #2a6fd6; }
#cfg > .hint { opacity: 0.65; font-size: 0.9em; margin-bottom: 0.4em; }
.stg summary { cursor: pointer; }
.stg .kind { font-size: 0.75em; padding: 0 0.35em; border-radius: 4px; border: 1px solid #8888; margin-right: 0.4em; }
.stg .kind.upd { color: #b07400; border-color: #b0740088; } .stg .kind.new { color: #27864a; border-color: #27864a88; }
.stg .fld { margin: 0.3em 0 0.5em 1em; } .stg .lbl { opacity: 0.7; font-size: 0.85em; }
.stg .fval { margin-top: 0.1em; overflow-wrap: anywhere; } .stg .fval ul, .stg .fval ol { margin: 0.2em 0; padding-left: 1.4em; }
.stg .fval table { border-collapse: collapse; } .stg .fval td, .stg .fval th { border: 1px solid #8886; padding: 0.15em 0.5em; }
.stg .fval code { background: #8882; padding: 0 0.25em; border-radius: 3px; } .stg .fval hr { opacity: 0.4; }
.stg .btns { margin-top: 0.8em; } .stg .btns button { margin: 0 0.5em 0 0; }
</style>
"""

JS = """
<script>
window.aiGen = {
  update(logHtml, refInfo, refBad, stagedHtml, status, busy, batching) {
    const log = document.getElementById("log");
    log.innerHTML = logHtml; log.scrollTop = log.scrollHeight;
    const info = document.getElementById("refinfo");
    info.textContent = refInfo; info.className = refBad ? "bad" : "";
    const stg = document.getElementById("sections");
    const open = new Set(Array.from(stg.querySelectorAll("details[open]")).map(d => d.dataset.id));
    stg.innerHTML = stagedHtml;
    stg.querySelectorAll("details").forEach(d => { if (open.has(d.dataset.id)) d.open = true; });
    stg.querySelectorAll(".card").forEach(c => { if (this.origs.has(c.dataset.card)) c.classList.add("orig"); });
    const st = document.getElementById("status");
    clearInterval(this.timer);
    if (busy) {
      const t0 = this.since = (this.busy ? this.since : Date.now());
      const tick = () => { st.textContent = "⏳ " + (status || "Working…") + " " + Math.round((Date.now() - t0) / 1000) + "s"; };
      tick(); this.timer = setInterval(tick, 1000);
    } else { st.textContent = status; }
    st.className = busy ? "busy" : "";
    this.busy = busy;
    document.getElementById("stop").style.display = batching ? "" : "none";
  },
  setRef(path) { document.getElementById("ref").value = path; },
  origs: new Set(),  // cards showing their original; kept across redraws
  toggleOrig(btn) {
    const card = btn.closest(".card");
    const on = card.classList.toggle("orig");
    card.querySelectorAll(on ? ".v-orig details" : ".v-upd details").forEach(d => { d.open = true; });  // full view
    if (on) this.origs.add(card.dataset.card); else this.origs.delete(card.dataset.card);
  },
};
</script>
"""


def _ids(text: str) -> list:
    """"12,34" from a button -> staged note ids."""
    return [int(x) for x in text.split(",") if x.strip().isdigit()]


class _Result:
    """CollectionOp wants an object with .changes; carry the counts along."""

    def __init__(self, pair):
        self.changes, self.info = pair


class GeneratePage(Tab):
    PREFIX = "aiGen"
    TITLE = "✨ Generate/Update"

    def __init__(self, addon: str, host):
        super().__init__(addon, host)
        self.replies = deque(maxlen=6)  # (text, "ai" | "err"): what Approve / Submit / Discard did
        self.ref = ""  # reference path as chosen (validated on every use)
        self.loaded = {}  # deck name -> [note dict] the AI asked to read
        self.busy = False  # a chat is working on cards: collection changes here wait for it
        self.status = ""  # what that chat is doing
        self.batching = False  # a request is being worked through in batches of cards
        self.stop_requested = False  # Stop was pressed: finish the current batch, then end
        self._ref_cache = (None, None)  # (path, (info, is_bad)): folders aren't rescanned on every redraw

    # --- for the chat (assistant.py) ---

    def references(self):
        """The chosen reference files, read now (None if none chosen); ValueError if they can't be used."""
        return generate_ops.read_references(self.ref) if self.ref.strip() else None

    def set_status(self, busy: bool, status: str = "", batching: bool = False):
        self.busy, self.status, self.batching = busy, status, batching
        if not busy:
            self.stop_requested = False
            if not self.shown():
                self.loaded = {}  # deck contents change elsewhere: re-read when next asked
        self._update()

    def refresh(self):
        self._update()

    # --- page ---

    def entered(self):
        self._ref_cache = (None, None)
        self._update()

    def left(self):
        if not self.busy:
            self.loaded = {}

    def _on_message(self, command: str, arg: str):
        if command == "clearref":
            self.ref = ""
            self._update()
        elif command in ("pickdir", "pickfile"):
            self._pick(command == "pickdir")
        elif command == "stop":
            self.stop_requested = True
            self.status = "Stopping after this batch…"
            self._update()
        elif self.busy:  # collection changes wait until the AI's reply has been applied
            self.say("The chat is still working on cards — try again when it's done.", err=True)
        elif command in ("approve", "unapprove"):
            ids = _ids(arg) if arg else None  # no ids = all staged cards
            ok = command == "approve"
            self.run_op(lambda col: _Result(generate_col.approve(col, ids, ok=ok)), lambda _n: self._update())
        elif command == "submit":
            self.run_op(lambda col: _Result(generate_col.submit(col)), self._submitted)
        elif command == "discard":
            ids = _ids(arg) if arg else None
            self.run_op(lambda col: _Result(generate_col.discard(col, ids)),
                         lambda n: self.say(f"Discarded {n} staged card{'s' if n != 1 else ''}. "
                                            "Edit → Undo brings them back."))

    def _pick(self, folder: bool):
        start = str(generate_ops.desktop())
        win = self.host.win or mw
        if folder:
            path = QFileDialog.getExistingDirectory(win, "Choose a reference folder on your Desktop", start)
        else:
            path = QFileDialog.getOpenFileName(win, "Choose a reference file on your Desktop", start)[0]
        if path:
            self.ref = path
            self.eval(f"window.aiGen && aiGen.setRef({json.dumps(path)});")
            self._update()

    def run_op(self, op, on_done, on_fail=None):
        def failed(e):
            if on_fail:
                on_fail()
            self.say(f"Couldn't change the collection: {e}", err=True)

        CollectionOp(parent=mw, op=op).success(lambda r: on_done(r.info)).failure(failed).run_in_background()

    def _submitted(self, counts):
        self.loaded = {}  # real decks changed: the AI re-reads them when needed
        left = len(generate_col.staged(mw.col))
        self.say(f"Submitted: {counts['updated']} card{'s' if counts['updated'] != 1 else ''} updated, "
                 f"{counts['added']} added to their decks."
                 + (f" {left} unapproved card{'s' if left != 1 else ''} still in {generate_ops.TEMP_DECK}." if left else "")
                 + " Edit → Undo reverses this.")

    # --- rendering ---

    def say(self, text: str, err: bool = False):
        self.replies.append((text, "err" if err else "ai"))
        self._update()

    def _update(self):
        if not self.shown():
            return
        info, bad = self._ref_info()
        args = [self._log_html(), info, bad, self._staged_html(), self.status if self.busy else "", self.busy,
                self.batching]
        self.eval(f"window.aiGen && aiGen.update({', '.join(json.dumps(a) for a in args)});")

    def _ref_info(self) -> tuple:
        if self._ref_cache[0] != self.ref:
            self._ref_cache = (self.ref, self._scan_ref())
        return self._ref_cache[1]

    def _scan_ref(self) -> tuple:
        if not self.ref.strip():
            return "Optional: a file or folder on your Desktop for the AI to make cards from (text files only).", False
        try:
            return "✓ " + generate_ops.ref_summary(generate_ops.read_references(self.ref)), False
        except ValueError as e:
            return f"✗ {e}", True

    def _log_html(self) -> str:
        return "".join(f'<div class="{kind}">&gt; {html.escape(t)}</div>' for t, kind in self.replies)

    def _staged_html(self) -> str:
        staged = generate_col.staged(mw.col)
        working = ('<div class="hint" style="color:#2a6fd6;opacity:1">⏳ Still working — more cards will appear below. '
                   'Submit and Approve all wait until it finishes.</div>' if self.batching else "")
        if not staged:
            return (f'<div class="sect stg"><h3>{TEMP}</h3>{working}'
                    f'<div style="opacity:.6">Nothing staged yet.</div></div>')
        out, deck = [], None
        for i, s in enumerate(staged, 1):
            if s["deck"] != deck:
                deck = s["deck"]
                in_deck = [x for x in staged if x["deck"] == deck]
                ids = ",".join(str(x["id"]) for x in in_deck)
                pending = ",".join(str(x["id"]) for x in in_deck if not x["ok"])
                approve = (f'<button onclick="pycmd(\'aiGen:approve:{pending}\')">Approve deck</button>' if pending
                          else f'<button onclick="pycmd(\'aiGen:unapprove:{ids}\')">Unapprove deck</button>')
                out.append(f'<div class="deck">{html.escape(deck or "(no deck)")}<span class="acts">{approve}'
                           f'<button onclick="pycmd(\'aiGen:discard:{ids}\')">Discard deck</button></span></div>')
            kind = ('<span class="kind upd">UPDATE</span>' if s["of"] else '<span class="kind new">NEW</span>')
            body = self._card_body(f'{i}. {kind}', s["fields"], str(s["id"]))
            original = self._original(s["of"])
            toggle = ""
            if original is not None:  # both versions rendered; the button swaps them in the page, no round-trip
                body = (f'<div class="v-upd">{body}</div><div class="v-orig">'
                        f'{self._card_body(f"{i}. <span class=kind>ORIGINAL</span>", original, "o" + str(s["id"]))}</div>')
                toggle = ('<button onclick="aiGen.toggleOrig(this)"><span class="l-upd">Show Original</span>'
                          '<span class="l-orig">Show Update</span></button>')
            approve = (f'<span class="okmark">✓ Approved</span>'
                      f'<button onclick="pycmd(\'aiGen:unapprove:{s["id"]}\')">Unapprove</button>' if s["ok"]
                      else f'<button onclick="pycmd(\'aiGen:approve:{s["id"]}\')">Approve</button>')
            acts = (f'<span class="acts">{approve}'
                    f'<button onclick="pycmd(\'aiGen:discard:{s["id"]}\')">Discard</button>{toggle}</span>')
            out.append(f'<div class="card{" ok" if s["ok"] else ""}" data-card="{s["id"]}">'
                       f'<div class="main">{body}</div>{acts}</div>')
        ok = sum(1 for s in staged if s["ok"])
        pending = len(staged) - ok
        submit = (f'<button class="submit" onclick="pycmd(\'aiGen:submit\')"{" disabled" if self.batching else ""}>'
                  f'Submit {ok} approved</button>' if ok
                  else '<button class="submit" disabled>Submit (approve cards first)</button>')
        buttons = (f'<div class="btns">'
                   + (f'<button onclick="pycmd(\'aiGen:approve\')"{" disabled" if self.batching else ""}>'
                      f'Approve all ({pending})</button>' if pending
                      else f'<button onclick="pycmd(\'aiGen:unapprove:{",".join(str(s["id"]) for s in staged)}\')">'
                           f'Unapprove all ({ok})</button>')
                   + f'<button onclick="pycmd(\'aiGen:discard\')">Discard all</button>{submit}</div>'
                   f'<div class="hint">Approved cards stay here until you Submit — keep generating meanwhile.</div>')
        return f'<div class="sect stg"><h3>{TEMP} — waiting for you</h3>{working}{"".join(out)}{buttons}</div>'

    @staticmethod
    def _card_body(prefix: str, fields: dict, key: str) -> str:
        """Question (first field) as the row, the other non-empty fields inside it when expanded."""
        values = list(fields.items())
        question = f'{prefix}<span class="q">{html.escape(strip_html(values[0][1]) if values else "")}</span>'
        rest = "".join(f'<div class="fld"><span class="lbl">{html.escape(k)}</span><div class="fval">{safe_html(v)}</div></div>'
                       for k, v in values[1:] if v.strip())  # the question is already in the summary
        return (f'<details data-id="{key}"><summary>{question}</summary>{rest}</details>' if rest
                else f'<div class="plain">{question}</div>')

    @staticmethod
    def _original(note_id):
        """The original note's fields for a staged update; None for new cards or a deleted original."""
        if not note_id:
            return None
        try:
            return dict(mw.col.get_note(note_id).items())
        except Exception:  # NotFoundError: original deleted meanwhile — Submit then adds the copy as new
            return None

    def page_html(self) -> str:
        return (
            f'{CSS}<div id="cfg"><h2>Generate/Update Cards</h2>'
            '<div class="hint">Tell the chat on the right what cards to make or fix — e.g. "10 cards from these notes '
            'into Biology::Ch3", "improve my Chem cards using this file", "make card 3 shorter". New and updated cards '
            'wait in the AI-GEN deck below until you approve and Submit them.</div>'
            f'<div id="log">{self._log_html()}</div>'
            f'<div id="refrow"><input id="ref" readonly tabindex="-1" value="{html.escape(self.ref)}" '
            f'placeholder="No reference chosen (optional)">'
            f'<button onclick="pycmd(\'aiGen:pickdir\')">Choose folder…</button>'
            f'<button onclick="pycmd(\'aiGen:pickfile\')">Choose file…</button>'
            f'<button title="Clear" onclick="aiGen.setRef(\'\');pycmd(\'aiGen:clearref\')">×</button></div>'
            f'<div id="refinfo"></div>'
            f'<div id="status"></div>'
            f'<button id="stop" style="display:none" onclick="pycmd(\'aiGen:stop\')">Stop after this batch</button>'
            f'<div id="sections"></div></div>{JS}'
        )
