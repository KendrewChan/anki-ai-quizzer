"""The AI chat panel on the right of an Anki window.

`Chat` is the page and its bridge (the conversation lives in the page, so it survives card changes).
`ReviewPanel` docks it in the main window (or any QMainWindow: Browse, Add Cards) and widens the window by its width,
so the card keeps its size and position."""

import json

from aqt import mw
from aqt.qt import QApplication, QCursor, QDockWidget, QEvent, QObject, QPushButton, Qt, QTimer, QWidget
from aqt.webview import AnkiWebView

from . import panel_page
from .textutil import rich

WIDTH = 380  # review panel width in px; the main window grows by this much
MIN_WIDTH = 260  # the dock can't be dragged narrower than this


class Chat:
    def __init__(self, on_send, on_close, hint: str, on_command=None, quick: bool = True):
        self.on_send = on_send  # (selection, text) -> None
        self.on_close = on_close
        self.on_command = on_command  # (command, arg) -> None: "clear", "act:<key>"
        self.web = AnkiWebView(title="ai study chat")
        self.web.set_bridge_command(self._on_bridge, self)
        self.web.stdHtml(panel_page.panel_html(hint, quick),
                         js=["js/mathjax.js", "js/vendor/mathjax/tex-chtml-full.js"],  # as the reviewer
                         context=self)

    def js(self, code: str):
        """Run `code` once the page's script has defined aiPanel (it may still be loading). Not a "ready" message
        from the page: an early pycmd can be lost, and everything after it would then wait forever."""
        self.web.eval("(function t() { if (window.aiPanel) { %s } else setTimeout(t, 100); })();" % code)

    def quote(self, selection: str):
        self.js(f"aiPanel.quote({json.dumps(selection)});")
        QTimer.singleShot(0, self.focus)

    def focus(self):
        """Put the keyboard in the chat box: the page's own focus() does nothing while another widget (the card, the
        note editor) still has Qt focus."""
        self.web.window().activateWindow()
        self.web.setFocus(Qt.FocusReason.OtherFocusReason)
        self.web.eval("document.getElementById('cmd') && document.getElementById('cmd').focus();")

    def reply(self, text: str, err: bool = False, actions=()):
        """actions: [(label, key)] shown as buttons under the reply; a click sends on_command("act", key)."""
        self.js(f"aiPanel.reply({json.dumps(rich(text))}, {json.dumps(err)}, {json.dumps(list(actions))});")

    def status(self, text: str):
        self.js(f"aiPanel.status({json.dumps(text)});")

    def prefill(self, prefix: str):
        self.js(f"aiPanel.prefill({json.dumps(prefix)});")
        QTimer.singleShot(0, self.focus)

    def unprefill(self):
        self.js("aiPanel.unprefill();")

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
        elif command in ("clear", "act") and self.on_command:
            self.on_command(command, arg)


class ReviewPanel:
    HINT = "Highlight text on the card and click the AI bubble, then ask. Your questions stay here as you review."

    def __init__(self, on_send, window=None, hint: str = HINT, on_command=None, quick: bool = True):
        """Docked in `window` (default: the main window). The user can drag the panel wider or narrower."""
        self.win = window or mw
        self.hint = hint
        self.on_send = on_send
        self.on_command = on_command
        self.quick = quick
        self.dock = None
        self.chat = None
        self.grown = 0  # px the window was widened by while the panel is open

    def _build(self):
        self.chat = Chat(self.on_send, self.close, self.hint, self.on_command, self.quick)
        self.dock = QDockWidget("AI Study", self.win)
        self.dock.setObjectName("aiStudyAskPanel")
        self.dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)  # no float / move; × is in the page
        self.dock.setTitleBarWidget(QWidget())  # empty: the page draws its own header
        self.dock.setWidget(self.chat.web)
        self.dock.setMinimumWidth(MIN_WIDTH)
        self.dock.resize(WIDTH, self.dock.height())
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
        shrink = self.dock.width()  # the user may have resized it
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

    def reply(self, text: str, err: bool = False, actions=()):
        if self.chat is not None:
            self.chat.reply(text, err, actions)

    def status(self, text: str):
        if self.chat is not None:
            self.chat.status(text)

    def has_focus(self) -> bool:
        """The keyboard is in the panel (the web view or its internal focus proxy)."""
        w = QApplication.focusWidget()
        return self.is_open() and w is not None and (w is self.chat.web or self.chat.web.isAncestorOf(w))


BROWSE_HINT = "Select text in the note and click the AI bubble, then ask. I can also edit the note's fields."
ADD_HINT = "Ask about the note you're writing: wording, what to put on the back, how to split it into cards. I can also fill in or change its fields."


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
