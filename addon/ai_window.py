"""🤖 AI Window: ⚙ Settings, ✨ Generate/Update and 📋 Today's Missed as tabs on the left, the AI chat docked on the
right. A window of its own, like Browse, so it can stay open while reviewing."""

import html

from aqt.qt import QMainWindow
from aqt.webview import AnkiWebView

from .assistant import Context, Conversation
from .config_page import ConfigPage
from .generate_page import GeneratePage
from .missed_page import MissedPage

WIDTH, HEIGHT = 900, 720  # the tabs' part; opening the chat widens the window by its width
HINT = ("Ask me anything — I can search the web, change settings, make or fix cards, and go through what you missed "
        "today.")
SECTION = {"settings": "settings", "generate": "cards", "missed": "missed"}  # loaded for each tab's messages

CSS = """
<style>
body { margin: 0; padding: 0; }
#shell { display: flex; min-height: 100vh; }
#nav { flex: none; width: 11.5em; box-sizing: border-box; padding: 1em 0.5em; border-right: 1px solid #8884;
       position: sticky; top: 0; height: 100vh; text-align: left; }
#nav a { display: block; padding: 0.45em 0.7em; margin-bottom: 2px; border-radius: 6px; cursor: pointer;
         color: inherit; text-decoration: none; }
#nav a:hover { background: #8882; } #nav a.on { background: #8883; font-weight: 600; }
#nav a.chat { margin-top: 1em; opacity: 0.8; }
#main { flex: 1; min-width: 0; }
</style>
"""


class _Window(QMainWindow):
    def __init__(self, on_close):
        super().__init__(None)
        self.on_close = on_close

    def closeEvent(self, event):
        self.on_close()
        super().closeEvent(event)


class AIWindow:
    def __init__(self, addon: str, on_config_changed):
        self.addon = addon
        self.settings = ConfigPage(addon, self, on_config_changed)
        self.generate = GeneratePage(addon, self)
        self.missed = MissedPage(addon, self)
        self.tabs = {"settings": self.settings, "generate": self.generate, "missed": self.missed}
        self.current = "settings"
        self.win = None  # built on first open, then hidden and shown again
        self.web = None
        self.chat = None

    def open(self, tab: str = None):
        if self.win is None:
            self._build()
        shown = self.win.isVisible()
        if tab in self.tabs and tab != self.current:
            if shown:
                self.tabs[self.current].left()
            self.current = tab
        elif shown:
            tab = None  # already there
        if not shown:
            self.win.show()
            self.chat.panel.open()
        if tab or not shown:
            self._render()
        self.win.raise_()
        self.win.activateWindow()

    def close(self):
        if self.win is not None and self.win.isVisible():
            self.win.close()

    def shows(self, tab) -> bool:
        return self.win is not None and self.win.isVisible() and self.tabs[self.current] is tab

    def prefill(self, prefix: str):
        """Start the chat box with `prefix` (the Settings tab's deck click)."""
        self.chat.panel.open()
        self.chat.panel.chat.prefill(prefix)

    def unprefill(self):
        if self.chat.panel.chat is not None:
            self.chat.panel.chat.unprefill()

    def _build(self):
        self.win = _Window(self._closed)
        self.win.setWindowTitle("AI Window")
        self.win.resize(WIDTH, HEIGHT)
        self.web = AnkiWebView(title="ai window")
        self.web.set_bridge_command(self._on_bridge, self)
        self.win.setCentralWidget(self.web)
        self.chat = Conversation(self.addon, self, self._context, HINT, window=self.win, quick=False)

    def _render(self):
        tab = self.tabs[self.current]
        nav = "".join(f'<a class="{"on" if name == self.current else ""}" '
                      f'onclick="pycmd(\'aiWin:tab:{name}\')">{html.escape(t.TITLE)}</a>'
                      for name, t in self.tabs.items())
        nav += '<a class="chat" onclick="pycmd(\'aiWin:chat\')" title="Show or hide the chat">💬 Chat</a>'
        self.web.stdHtml(f'{CSS}<div id="shell"><nav id="nav">{nav}</nav><div id="main">{tab.page_html()}</div></div>',
                         context=self)
        tab.entered()

    def _on_bridge(self, message: str):
        if message.startswith("aiWin:tab:"):
            self.open(message[len("aiWin:tab:"):])
        elif message == "aiWin:chat":
            self.chat.panel.toggle()
        else:
            self.tabs[self.current].on_bridge(message)

    def _closed(self):
        """Closing forgets the conversation; staged cards, the reference and settings stay."""
        self.tabs[self.current].left()
        self.chat.forget()

    def _context(self, _selection: str, done):
        name = self.current
        done(Context(f"the AI Window, {self.tabs[name].TITLE} tab", [SECTION[name]],
                     deck=self.settings.selected if name == "settings" else None))
