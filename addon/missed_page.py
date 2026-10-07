"""📋 Today's Missed: the AI Window's read-only tab listing the notes whose Missed section was written today, by deck."""

import datetime
import html

from aqt import mw

from . import missed_today
from .missed import _count_html
from .tab_page import CSS as TAB_CSS, Tab

CSS = TAB_CSS + """
<style>
#cfg .deck { font-weight: 600; margin: 1em 0 0.2em; }
#cfg .note { margin: 0.3em 0 0.6em 1em; } #cfg .front { opacity: 0.75; font-size: 0.9em; }
#cfg .note ul { margin: 0.1em 0 0; padding-left: 1.4em; }
</style>
"""


class MissedPage(Tab):
    PREFIX = "aiMissed"
    TITLE = "📋 Today's Missed"

    def page_html(self) -> str:
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
        return f"{CSS}<div id=\"cfg\"><h2>📋 Today's Missed ({today})</h2>{''.join(body)}</div>"

