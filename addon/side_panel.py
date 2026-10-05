"""The AI chat panel on the right of an Anki window.

`Chat` is the page and its bridge (the conversation lives in the page, so it survives card changes).
`ReviewPanel` docks it in the main window and widens the window by its width, so the card keeps its size and position.
`AddPanel` attaches it to the right edge of the Add Cards window and follows that window around."""

import json

from aqt import mw
from aqt.qt import QApplication, QCursor, QDockWidget, QEvent, QObject, QPushButton, Qt, QTimer, QVBoxLayout, QWidget
from aqt.webview import AnkiWebView

from . import panel_page
from .textutil import rich

WIDTH = 380  # review panel width in px; the main window grows by this much
ADD_WIDTH = 340
MIN_WIDTH = 260  # a resizable dock can't be dragged narrower than this


class Chat:
    def __init__(self, on_send, on_close, hint: str):
        self.on_send = on_send  # (selection, text) -> None
        self.on_close = on_close
        self.web = AnkiWebView(title="ai study chat")
        self.web.set_bridge_command(self._on_bridge, self)
        self.web.stdHtml(panel_page.panel_html(hint), js=["js/mathjax.js", "js/vendor/mathjax/tex-chtml-full.js"],  # as the reviewer
                         context=self)

    def js(self, code: str):
        """Run `code` once the page's script has defined aiPanel (it may still be loading). Not a "ready" message
        from the page: an early pycmd can be lost, and everything after it would then wait forever."""
        self.web.eval("(function t() { if (window.aiPanel) { %s } else setTimeout(t, 100); })();" % code)

    def quote(self, selection: str):
        self.js(f"aiPanel.quote({json.dumps(selection)});")

    def reply(self, text: str, err: bool = False):
        self.js(f"aiPanel.reply({json.dumps(rich(text))}, {json.dumps(err)});")

    def clear(self):
        self.js("aiPanel.clear();")

    def _on_bridge(self, message: str):
        command, _, arg = message.partition(":")
        if command == "hide":  # the × in the page
            try:
                self.on_close()
            except Exception as e:
                self.reply(f"Couldn't close: {type(e).__name__}: {e}", True)
        elif command == "send":
            try:
                data = json.loads(arg)
                self.on_send(str(data.get("sel", "")), str(data.get("text", "")).strip())
            except Exception as e:  # never leave the page on "Thinking…"
                self.reply(f"Failed: {type(e).__name__}: {e}", True)


class ReviewPanel:
    HINT = "Highlight text on the card and click the AI bubble, then ask. Your questions stay here as you review."

    def __init__(self, on_send, window=None, hint: str = HINT):
        """Docked in `window` (default: the main window). Another window's panel can be resized by the user; the
        main window's is fixed, so the card keeps its size."""
        self.win = window or mw
        self.resizable = window is not None
        self.hint = hint
        self.on_send = on_send
        self.dock = None
        self.chat = None
        self.grown = 0  # px the window was widened by while the panel is open

    def _build(self):
        self.chat = Chat(self.on_send, self.close, self.hint)
        self.dock = QDockWidget("AI Study", self.win)
        self.dock.setObjectName("aiStudyAskPanel")
        self.dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)  # no float / move; × is in the page
        self.dock.setTitleBarWidget(QWidget())  # empty: the page draws its own header
        self.dock.setWidget(self.chat.web)
        if self.resizable:
            self.dock.setMinimumWidth(MIN_WIDTH)
            self.dock.resize(WIDTH, self.dock.height())
        else:
            self.dock.setFixedWidth(WIDTH)
        self.win.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)

    def is_open(self) -> bool:
        return self.dock is not None and not self.dock.isHidden()

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
        shrink = self.dock.width() if self.resizable else self.grown  # the user may have resized it
        self.dock.hide()
        if self.grown:
            self.win.resize(max(self.win.minimumWidth(), self.win.width() - shrink), self.win.height())
        self.grown = 0
        if self.win is mw:
            QTimer.singleShot(0, self._focus_card)

    @staticmethod
    def _focus_card():
        """Hand focus back to the card without letting the page pick a control (it would highlight "Show original")."""
        mw.web.setFocus(Qt.FocusReason.OtherFocusReason)
        mw.web.eval("document.activeElement && document.activeElement.blur && document.activeElement.blur();")

    def reset(self):
        """The review session ended: forget the conversation and give the width back."""
        self.close()
        if self.chat is not None:
            self.chat.clear()

    def _grow(self, width: int) -> int:
        """Widen the window by up to `width` px (keeping it on screen); returns what it actually grew by."""
        win = self.win
        if win.isMaximized() or win.isFullScreen():
            return 0  # no room to grow: the card area gives way instead
        before = win.width()
        screen = win.screen().availableGeometry()
        room = screen.right() + 1 - win.frameGeometry().left()
        if room < before + width:  # not enough space to the right: slide left first
            win.move(max(screen.left(), win.x() - (before + width - room)), win.y())
            room = screen.right() + 1 - win.frameGeometry().left()
        win.resize(min(before + width, room), win.height())
        return max(0, win.width() - before)

    def show_selection(self, selection: str):
        self.open()
        self.chat.quote(selection)

    def toggle(self):
        self.close() if self.is_open() else self.open()

    def reply(self, text: str, err: bool = False):
        if self.chat is not None:
            self.chat.reply(text, err)


BROWSE_HINT = "Select text in the note and click the AI bubble, then ask. I can also edit the note's fields."


class AddPanel(QObject):
    """A panel stuck to the right edge of the Add Cards or Browse window, opened and closed from there."""
    HINT = "Ask about the note you're writing: wording, what to put on the back, how to split it into cards."

    def __init__(self, dialog, on_send, hint: str = HINT):
        super().__init__(dialog)
        self.dialog = dialog
        self.box = QWidget(dialog, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.chat = Chat(on_send, self.close, hint)
        layout = QVBoxLayout(self.box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.chat.web)
        dialog.installEventFilter(self)

    def is_open(self) -> bool:
        return not self.box.isHidden()

    def toggle(self):
        self.close() if self.is_open() else self.open()

    def open(self):
        d = self.dialog
        screen = d.screen().availableGeometry()
        over = d.frameGeometry().right() + 1 + ADD_WIDTH - (screen.right() + 1)
        if over > 0 and not d.isMaximized():  # no room on the right: slide the window left
            d.move(max(screen.left(), d.x() - over), d.y())
        self._place()
        self.box.show()

    def close(self):
        self.box.hide()

    def _place(self):
        g = self.dialog.frameGeometry()
        self.box.setGeometry(g.right() + 1, g.top(), ADD_WIDTH, g.height())

    def show_selection(self, selection: str):
        self.open()
        self.chat.quote(selection)

    def reply(self, text: str, err: bool = False):
        self.chat.reply(text, err)

    def eventFilter(self, obj, event):
        if obj is self.dialog and not self.box.isHidden():
            t = event.type()
            if t in (QEvent.Type.Move, QEvent.Type.Resize):
                self._place()
            elif t in (QEvent.Type.Hide, QEvent.Type.Close):
                self.box.hide()
        return False


class SelectionBubble(QObject):
    """A small "AI" button that appears at the mouse after text is selected in `web` (the Browse editor, where the
    page can't be scripted like the reviewer's); clicking it passes the selection to `on_ask`."""

    def __init__(self, web, on_ask):
        super().__init__(web)
        self.web = web
        self.on_ask = on_ask
        self.text = ""
        self.button = QPushButton("AI", web.window())
        # The bubble must never take focus: when the Browse window loses it, the editor drops its selection highlight.
        self.button.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                                   | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.button.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.button.setStyleSheet("QPushButton { background:#2a6fd6; color:white; border-radius:8px; padding:3px 9px; "
                                  "font-weight:600; }")
        self.button.clicked.connect(self._ask)
        QApplication.instance().installEventFilter(self)

    def _ask(self):
        self.button.hide()
        if self.text:
            self.on_ask(self.text)

    def _check(self):
        self.text = self.web.selectedText().strip()
        if not self.text or not self.web.isVisible():
            self.button.hide()
            return
        self.button.adjustSize()
        pos = QCursor.pos()
        self.button.move(pos.x() + 8, pos.y() - self.button.height() - 8)
        self.button.show()

    def eventFilter(self, obj, event):
        t = event.type()
        if t == QEvent.Type.MouseButtonRelease and isinstance(obj, QWidget) and (
                obj is self.web or self.web.isAncestorOf(obj)):
            QTimer.singleShot(50, self._check)  # the page updates its selection just after the release
        elif t == QEvent.Type.MouseButtonPress and self.button.isVisible():
            # Qt delivers the press to the bubble's window object, not the button, so compare positions instead.
            if not self.button.frameGeometry().contains(event.globalPosition().toPoint()):
                self.button.hide()
        return False

    def close(self):
        QApplication.instance().removeEventFilter(self)
        self.button.hide()
