"""The AI chat in a side panel, one per window: the AI Window, the reviewer, Browse, Add Cards. Each message is a fresh
CLI call that may search and fetch the web; nothing is remembered but the last few exchanges, resent as text. The
window says what the user has open (`context`); the AI loads other sections with "need". Prompts: assistant_ops."""

import datetime
import tempfile
from collections import deque

from aqt import mw

from . import assistant_ops, generate_col, generate_ops, health, missed_today, note_chat
from .config_ops import settings_context
from .generate_page import _Result
from .session import make_backend, model_for, provider_of, resolved_model
from .side_panel import ReviewPanel
from .tab_page import deck_ids, load_config

TIMEOUT_S = 300  # web searches and big card requests take a while


class Context:
    """What the user has open when they send a message.

    where: one line for the AI. sections: loaded from the start. note: the NOTE section, when a note is open.
    apply_fields(fields, reply, say): writes the AI's field changes into that note and reports through say(text, err).
    deck: the deck "this deck" means (the Settings tab's selection, the card's deck)."""

    def __init__(self, where: str, sections=(), note: str = None, apply_fields=None, deck: str = None):
        self.where = where
        self.sections = set(sections)
        self.note = note
        self.apply_fields = apply_fields
        self.deck = deck


class _Turn:
    """One user message, through all its AI calls."""

    def __init__(self, ctx: Context, text: str, sel: str):
        self.ctx, self.text, self.sel = ctx, text, sel
        self.rounds = 0
        self.found = ""  # search results appended to the message
        self.searched = ()
        self.staged = []  # AI-GEN as listed in the last prompt (staged card numbers refer to it)
        self.batch = None  # (index, chunks) while a per-card request goes through the cards a few at a time
        self.tally = None  # counts, rejected changes and last reply over the batches
        self.owns_cards = False  # holds the Generate/Update tab's busy flag
        self.forget = False  # Clear was pressed meanwhile: keep it out of the history


class Conversation:
    def __init__(self, addon: str, host, context, hint: str, window=None, quick: bool = True):
        """host: the AI Window (its Settings and Generate/Update tabs). context(selection, done) calls done(Context),
        or done("<why not>") when the chat can't be used there right now."""
        self.addon = addon
        self.host = host
        self.context = context
        self.panel = ReviewPanel(self.send, window, hint, self._on_command, quick)
        self.history = deque(maxlen=assistant_ops.HISTORY)  # (user message, reply)
        self.turn = None  # the message being answered
        self.backend = None
        self.cwd = None
        self._actions = {}  # button key -> callable, for buttons under replies
        self._next_key = 0

    # --- panel ---

    def send(self, sel: str, text: str):
        def done(ctx):
            try:
                if isinstance(ctx, str):
                    self.panel.reply(ctx, True)
                    return
                self.cancel()  # after Clear the panel takes a new message while the last one may still run
                self.turn = _Turn(ctx, text, sel)
                self._ask(self.turn)
            except Exception as e:  # runs in Qt callbacks, where errors would vanish and leave the panel on "Thinking…"
                self.turn = None
                self.panel.reply(f"Failed: {type(e).__name__}: {e}", True)

        try:
            self.context(sel, done)
        except Exception as e:
            self.panel.reply(f"Failed: {type(e).__name__}: {e}", True)

    def _on_command(self, command: str, arg: str):
        if command == "clear":  # the page already emptied itself; a reply still coming is dropped there
            self.history.clear()
            if self.turn is not None:
                self.turn.forget = True
        elif command == "act":
            fn = self._actions.pop(arg, None)
            if fn:
                fn()

    def forget(self):
        """Empty the conversation and hide the panel (nothing is kept). A message still being answered finishes."""
        self.history.clear()
        if self.turn is not None:
            self.turn.forget = True
        self.panel.reset()

    def reset(self):
        """forget(), and stop a message being answered."""
        self.cancel()
        self.forget()

    def cancel(self):
        t, self.turn = self.turn, None
        if t is not None and t.owns_cards:
            self.host.generate.set_status(False)
        self._stop()

    def _stop(self):
        if self.backend is not None:
            self.backend.close()
            self.backend = None

    def _tmpdir(self) -> str:
        self.cwd = self.cwd or tempfile.mkdtemp(prefix="anki_ai_chat_")
        return self.cwd

    # --- one message ---

    def _ask(self, t: _Turn):
        gen = self.host.generate
        if "cards" in t.ctx.sections and not t.owns_cards:
            if gen.busy:
                self._finish(t, "Another chat is still working on cards — try again when it's done.", err=True)
                return
            t.owns_cards = True
            gen.set_status(True, "Thinking…")
        try:
            blocks = self._blocks(t)
        except ValueError as e:  # the chosen reference files can't be read
            self._finish(t, f"Reference: {e}", err=True)
            return
        extra = t.found + (f"\n\n{generate_ops.batch_line(t.batch[0], len(t.batch[1]))}" if t.batch else "")
        prompt = assistant_ops.message(t.ctx.where, blocks, t.text, t.sel, list(self.history), extra)
        self._stop()  # fresh process per call: the sections differ, and nothing is to be remembered
        self.backend = make_backend(load_config(self.addon), assistant_ops.system_prompt(t.ctx.sections),
                                    self._tmpdir(), mw.taskman.run_on_main, web=True)
        self.backend.request(0, prompt, assistant_ops.parse_reply, TIMEOUT_S,
                             lambda _id, result, err: self._on_reply(t, result, err))

    def _blocks(self, t: _Turn) -> dict:
        cfg, decks, s = load_config(self.addon), deck_ids(), t.ctx.sections
        blocks = {}
        if "settings" in s:
            provider = provider_of(cfg)
            blocks["settings"] = settings_context(cfg, self.host.settings.auth, decks,
                                                  t.ctx.deck if t.ctx.deck in decks else None,
                                                  resolved_model(provider, model_for(cfg)))
        if "cards" in s:
            gen = self.host.generate
            existing = gen.loaded
            if t.batch:
                index, chunks = t.batch
                existing = {}
                for n in chunks[index]:
                    existing.setdefault(n["deck"], []).append(n)
            prompts = cfg.get("deck_prompts") or {}
            rules = [(name, prompts[i].strip()) for name, i in decks.items() if str(prompts.get(i, "")).strip()]
            t.staged = generate_col.staged(mw.col)
            blocks["cards"] = generate_ops.cards_context(list(decks), gen.references(), existing, t.staged, rules)
        if "missed" in s:
            today = datetime.date.today().isoformat()  # the clock that stamps the Missed section
            blocks["missed"] = assistant_ops.missed_context(missed_today.missed_on(mw.col, today), today)
        if "note" in s and t.ctx.note:
            blocks["note"] = t.ctx.note
        return blocks

    def _progress(self, t: _Turn, text: str):
        self.panel.status(text)
        if t.owns_cards:
            self.host.generate.set_status(True, text, batching=bool(t.batch))

    def _on_reply(self, t: _Turn, result, err):
        if t is not self.turn:
            return  # cancelled meanwhile
        self._stop()
        if err:
            health.LAST_ERROR[provider_of(load_config(self.addon))] = err.message
            lost = ""
            if t.batch:
                index, chunks = t.batch
                lost = (f" Stopped at batch {index + 1} of {len(chunks)}: "
                        f"{sum(len(c) for c in chunks[:index])} of {sum(map(len, chunks))} cards done.")
            self._finish(t, f"AI error: {err.message} — the AI Window's Settings tab can fix it.{lost}", err=True)
            return
        t.rounds += 1
        more = t.rounds < assistant_ops.MAX_ROUNDS and not t.batch  # a batch only applies its changes
        acts = result["settings"] or result["cards"] or result["fields"]
        need = [n for n in result["need"] if n in assistant_ops.NEEDABLE and n not in t.ctx.sections]
        if need and more:
            t.ctx.sections |= set(need)
            self._progress(t, f"Loading {', '.join(need)}…")
            self._ask(t)
            return
        query = result["search"]
        if query and not acts and more and len(t.searched) < note_chat.MAX_SEARCHES:
            t.searched += (query,)
            t.found += search_notes(query, last=len(t.searched) >= note_chat.MAX_SEARCHES)
            self._progress(t, f"Searching your notes: {query}")
            self._ask(t)
            return
        rejected = []
        if "cards" in t.ctx.sections and not t.batch and self._read_decks(t, result, rejected):
            return
        ops = []
        if result["settings"]:
            if "settings" in t.ctx.sections:
                rejected += self.host.settings.apply_from_chat(result["settings"])
            else:
                rejected.append("✗ settings changes ignored: settings weren't loaded")
        if result["cards"]:
            if "cards" in t.ctx.sections:
                gen = self.host.generate
                existing = {n["id"]: n for notes in gen.loaded.values() for n in notes}
                ops, bad = generate_ops.plan_changes(result["cards"], list(deck_ids()), existing, t.staged)
                rejected += bad
            else:
                rejected.append("✗ card changes ignored: cards weren't loaded")
        fields = result["fields"]
        if fields and not (t.ctx.apply_fields and "note" in t.ctx.sections):
            rejected.append("✗ field changes ignored: no note can be changed here")
            fields = {}
        reply = result["reply"]

        def after_cards(counts=None):
            if t is not self.turn:
                return
            if t.batch:
                self._batch_done(t, counts, rejected, reply)
            else:
                self._done(t, reply, rejected, counts, fields)

        def failed():
            if t is self.turn:
                self._finish(t, "Couldn't stage the cards — see the Generate/Update tab.", err=True)

        if ops:
            self.host.generate.run_op(lambda col: _Result(generate_col.apply_ops(col, ops)), after_cards, failed)
        else:
            after_cards()

    def _read_decks(self, t: _Turn, result, rejected: list) -> bool:
        """Load the decks the AI asked to read. True when the message goes back to it with them (False: answer as is)."""
        gen = self.host.generate
        decks = list(deck_ids())
        new_reads = []
        for name in result["read_decks"]:
            try:
                name = generate_ops.resolve_read(name, decks)
            except ValueError as e:
                rejected.append(f"✗ {e}")
                continue
            if name not in gen.loaded:
                gen.loaded[name] = generate_col.read_deck(mw.col, name)
                new_reads.append(name)
        if not new_reads or result["cards"] or t.rounds >= assistant_ops.MAX_ROUNDS:
            return False
        chunks = generate_ops.chunk_notes(gen.loaded)
        if result["per_card"] and len(chunks) > 1:  # the same request, a few cards at a time
            t.batch, t.tally = (0, chunks), {"counts": {}, "rejected": [], "reply": ""}
            self._progress(t, self._batch_status(t))
        else:
            self._progress(t, "Reading your decks…")
        self._ask(t)
        return True

    @staticmethod
    def _batch_status(t: _Turn) -> str:
        index, chunks = t.batch
        done = sum(len(c) for c in chunks[:index])
        return f"Batch {index + 1} of {len(chunks)} — {done} of {sum(map(len, chunks))} cards done"

    def _batch_done(self, t: _Turn, counts, rejected: list, reply: str):
        """One batch was applied (and is on the Generate/Update tab): start the next, or finish."""
        index, chunks = t.batch
        tally = t.tally
        for k, v in (counts or {}).items():
            tally["counts"][k] = tally["counts"].get(k, 0) + v
        tally["rejected"] += rejected
        tally["reply"] = reply
        if index + 1 < len(chunks) and not self.host.generate.stop_requested:
            t.batch = (index + 1, chunks)
            self._progress(t, self._batch_status(t))
            self._ask(t)
            return
        total = sum(map(len, chunks))
        done = sum(len(c) for c in chunks[:index + 1])
        head = (f"Done: {total} cards processed in {len(chunks)} batches." if done == total else
                f"Stopped after batch {index + 1} of {len(chunks)}: {done} of {total} cards processed, "
                f"{total - done} not.")
        staged = self._staged_note(tally["counts"])
        self._finish(t, " ".join([head + staged, *tally["rejected"]]), err=bool(tally["rejected"]),
                     actions=self._review_action(tally["counts"]), remember=f"{head} {tally['reply']}".strip())

    def _done(self, t: _Turn, reply: str, rejected: list, counts, fields: dict):
        text = (reply or ("" if fields else "Done." if counts or rejected else "…")) + self._staged_note(counts)
        if t.searched:
            text += f" (Searched: {'; '.join(t.searched)})"
        text = " ".join(filter(None, [text, *rejected]))
        actions = self._review_action(counts)
        if fields:
            t.ctx.apply_fields(fields, text, lambda msg, err: self._finish(t, msg, err, actions, remember=text))
        else:
            self._finish(t, text, bool(rejected), actions)

    @staticmethod
    def _staged_note(counts) -> str:
        parts = [f"{v} {k}" for k, v in (counts or {}).items() if v]
        return f" ({', '.join(parts)} — staged in AI-GEN)" if parts else ""

    def _review_action(self, counts) -> list:
        if not any((counts or {}).values()):
            return []
        return [("Review in Generate/Update", lambda: self.host.open("generate"))]

    def _finish(self, t: _Turn, text: str, err: bool = False, actions=(), remember: str = None):
        if t is not self.turn:
            return
        self.turn = None
        if t.owns_cards:
            self.host.generate.set_status(False)
        if not err and not t.forget:
            self.history.append((t.text, remember or text))
        keys = []
        for label, fn in actions:
            self._next_key += 1
            self._actions[str(self._next_key)] = fn
            keys.append((label, str(self._next_key)))
        self.panel.reply(text, err, keys)


def search_notes(query: str, last: bool) -> str:
    """The AI's Anki search query run on the collection -> the text block for its next prompt."""
    try:
        ids = mw.col.find_notes(query)
        notes = []
        for nid in ids[:note_chat.MAX_RESULTS]:
            n = mw.col.get_note(nid)
            cards = n.cards()
            deck = mw.col.decks.name(cards[0].odid or cards[0].did) if cards else "?"
            notes.append({"deck": deck, "type": n.note_type()["name"], "fields": dict(n.items())})
        return note_chat.search_block(query, notes, len(ids), last)
    except Exception as e:  # a bad search syntax is the AI's to fix, not a failure of the chat
        return note_chat.search_block(query, [], 0, last, error=str(e))
