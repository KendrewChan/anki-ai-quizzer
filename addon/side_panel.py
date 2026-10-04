"""Highlight-to-ask chat: a panel docked on the right of Anki's main window.

Opening it widens the window by the panel's width, so the card keeps its size and position; closing it gives the
width back. The conversation lives in the panel's page, so it survives card changes until the review session ends."""

import json

from aqt import mw
from aqt.qt import QDockWidget, Qt, QWidget
from aqt.webview import AnkiWebView

from . import grading, ui

WIDTH = 380  # panel width in px; the window grows by this much


class AskPanel:
    def __init__(self, on_send):
        self.on_send = on_send  # (selection, text) -> None
        self.dock = None
        self.web = None
        self.grown = 0  # px the window was widened by while the panel is open
        self.ready = False  # page loaded, so JS calls work
        self.pending = []  # JS to run once the page has loaded

    def _build(self):
        self.dock = QDockWidget("AI Study", mw)
        self.dock.setObjectName("aiStudyAskPanel")
        self.dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)  # no float / move; × is in the page
        self.dock.setTitleBarWidget(QWidget())  # empty: the page draws its own header
        self.web = AnkiWebView(title="ai study chat")
        self.web.set_bridge_command(self._on_bridge, self)
        self.web.stdHtml(ui.PANEL_HTML, js=["js/mathjax.js", "js/vendor/mathjax/tex-chtml-full.js"], context=self)  # as the reviewer loads it
        self.dock.setWidget(self.web)
        self.dock.setFixedWidth(WIDTH)
        mw.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)

    def is_open(self) -> bool:
        return self.dock is not None and self.dock.isVisible()

    def open(self):
        if self.dock is None:
            self._build()
        if self.is_open():
            return
        self.grown = self._grow(WIDTH)
        self.dock.show()

    def close(self):
        if not self.is_open():
            return
        self.dock.hide()
        if self.grown:
            mw.resize(max(mw.minimumWidth(), mw.width() - self.grown), mw.height())
        self.grown = 0

    def reset(self):
        """The review session ended: forget the conversation and give the width back."""
        self.close()
        if self.web is not None:
            self.js("aiPanel.clear();")

    def _grow(self, width: int) -> int:
        """Widen the window by up to `width` px (keeping it on screen); returns what it actually grew by."""
        if mw.isMaximized() or mw.isFullScreen():
            return 0  # no room to grow: the card area gives way instead
        before = mw.width()
        screen = mw.screen().availableGeometry()
        room = screen.right() + 1 - mw.frameGeometry().left()
        if room < before + width:  # not enough space to the right: slide left first
            mw.move(max(screen.left(), mw.x() - (before + width - room)), mw.y())
            room = screen.right() + 1 - mw.frameGeometry().left()
        mw.resize(min(before + width, room), mw.height())
        return max(0, mw.width() - before)

    # --- page <-> Python ---

    def js(self, code: str):
        if self.web is None:
            return
        if self.ready:
            self.web.eval(code)
        else:
            self.pending.append(code)  # the page says "ready" when it has loaded

    def show_selection(self, selection: str):
        self.open()
        self.js(f"aiPanel.prefill({json.dumps(ui.prefix_for(selection))}, {json.dumps(selection)});")

    def reply(self, text: str, err: bool = False):
        self.js(f"aiPanel.reply({json.dumps(grading.rich(text))}, {json.dumps(err)});")

    def _on_bridge(self, message: str):
        command, _, arg = message.partition(":")
        if command == "ready":
            self.ready = True
            for code in self.pending:
                self.web.eval(code)
            self.pending = []
        elif command == "close":
            self.close()
        elif command == "send":
            data = json.loads(arg)
            self.on_send(str(data.get("sel", "")), str(data.get("text", "")).strip())

