"""📋 Today's Missed: a read-only page listing the notes whose Missed section was written today, by deck."""

import datetime
import html

from aqt import mw

from . import missed_today
from .missed import _count_html
from .chat_page import CSS as CHAT_CSS

CSS = CHAT_CSS + """
<style>
#cfg .deck { font-weight: 600; margin: 1em 0 0.2em; }
#cfg .note { margin: 0.3em 0 0.6em 1em; } #cfg .front { opacity: 0.75; font-size: 0.9em; }
#cfg .note ul { margin: 0.1em 0 0; padding-left: 1.4em; }
</style>
"""


class MissedPage:
    STATE = "aiStudyMissed"
    PREFIX = "aiMissed"

    def __init__(self, addon: str):
        setattr(mw, f"_{self.STATE}State", self._enter)
        setattr(mw, f"_{self.STATE}Cleanup", self._leave)

    def open(self):
        mw.moveToState(self.STATE)

    def _enter(self, _old_state, *_args):
        mw.bottomWeb.hide()
        mw.web.stdHtml(self._page_html(), context=self)
        mw.web.set_bridge_command(self._on_bridge, self)

    def _leave(self, _new_state):
        mw.bottomWeb.show()

    def _on_bridge(self, message: str):
        if message == f"{self.PREFIX}:back":
            mw.moveToState("deckBrowser")

    def _page_html(self) -> str:
        today = datetime.date.today().isoformat()  # the same clock that stamps the Missed section
        decks = missed_today.missed_on(mw.col, today)
        body = []
        for deck, notes in decks:
            body.append(f'<div class="deck">{html.escape(deck)}</div>')
            for n in notes:
                lis = "".join(f"<li>{_count_html(c)} {h}</li>" for h, c in n["items"])  # h is already safe HTML
                body.append(f'<div class="note"><div class="front">{html.escape(n["front"])} '
                            f'<i>({n["reviews"]} review{"s" if n["reviews"] != 1 else ""})</i></div><ul>{lis}</ul></div>')
        if not body:
            body.append("<p>Nothing missed today yet.</p>")
        return (f'{CSS}<div id="cfg"><a class="back" onclick="pycmd(\'{self.PREFIX}:back\')">← Back</a>'
                f"<h2>📋 Today's Missed ({today})</h2>{''.join(body)}</div>")

