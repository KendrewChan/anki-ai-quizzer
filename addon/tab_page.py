"""Shared by the AI Window's tabs (⚙ Settings, ✨ Generate/Update, 📋 Today's Missed), plus Anki helpers."""

import tempfile

from aqt import mw

from . import state, synced


def load_config(addon: str) -> dict:
    """The user's settings: this computer's (meta.json) plus those synced with the collection (see synced.py).
    Keys added after they were saved are missing: read them with defaults."""
    local = mw.addonManager.getConfig(addon) or {}
    if mw.col is None:
        return local
    migrate_once(addon)
    return synced.load(mw.col, local)


def migrate_once(addon: str, after_sync: bool = False):
    """Once per profile on this computer, merge the settings older versions kept in meta.json into the collection.
    With auto sync on, wait for the startup sync, so other devices' settings are in the collection to merge with
    (writing first would make this collection the newer one and its config would overwrite theirs)."""
    if mw.col is None or state.get("synced", mw.pm.name) or (not after_sync and mw.can_auto_sync()):
        return
    # only what the user saved: a fresh install's defaults must not overwrite another device's settings
    synced.migrate(mw.col, (mw.addonManager.addonMeta(addon) or {}).get("config") or {})
    state.put("synced", mw.pm.name, True)


def save_config(addon: str, cfg: dict, before: dict):
    """meta.json keeps this computer's settings; deck and general settings go into the collection (only what changed
    since `before`). Settings older versions kept in meta.json stay there untouched (other profiles may still need
    migrating)."""
    old = (mw.addonManager.addonMeta(addon) or {}).get("config") or {}
    legacy = {k: v for k, v in old.items() if k not in synced.local_part(old)}
    mw.addonManager.writeConfig(addon, {**legacy, **synced.local_part(cfg)})
    synced.save(mw.col, cfg, before)


def deck_ids() -> dict:
    """Full deck name -> deck id (str), the shape config_ops expects."""
    return {d.name: str(d.id) for d in mw.col.decks.all_names_and_ids(skip_empty_default=True)}  # as Anki's deck list


CSS = """
<style>
#cfg { max-width: 52em; margin: 1.2em auto; padding: 0 1em; text-align: left; }
#cfg h2 { margin: 0.4em 0 0.6em; }
#log { max-height: 34vh; overflow-y: auto; font-size: 0.92em; margin-bottom: 0.5em; }
#log .you { margin-top: 0.6em; font-weight: 600; padding-left: 1.2em; text-indent: -1.2em; }
#log .you::before { content: "> "; }
#log .ai, #log .err { margin: 0.2em 0 0; padding-left: 1.2em; text-indent: -1.2em; white-space: pre-wrap; }  /* hanging prefix */
#log .ai::before, #log .err::before { content: "● "; }
#log .err { color: #d33; }
#status { font-size: 0.85em; opacity: 0.7; min-height: 1.3em; margin: 0.3em 0 0.8em; }
.sect h3 { margin: 1em 0 0.3em; font-size: 1em; text-transform: uppercase; letter-spacing: 0.05em; opacity: 0.7; }
.sect table { border-collapse: collapse; } .sect td { padding: 0.15em 1.2em 0.15em 0; vertical-align: top; }
.sect button { margin-left: 0.6em; } .sect select { font: inherit; }
</style>
"""


class Tab:
    """A tab of the AI Window (`host`, ai_window.py). Its page talks back through "<PREFIX>:<command>:<arg>" bridge
    messages. Subclasses implement page_html and _on_message(command, arg), and may override entered / left."""

    PREFIX = ""
    TITLE = ""

    def __init__(self, addon: str, host):
        self.addon = addon
        self.host = host
        self.cwd = None  # empty temp dir the AI CLI runs in (model lookups)

    def cfg(self) -> dict:
        return load_config(self.addon)

    def tmpdir(self) -> str:
        self.cwd = self.cwd or tempfile.mkdtemp(prefix=f"anki_ai_{self.PREFIX}_")
        return self.cwd

    def shown(self) -> bool:
        """This tab is on screen."""
        return self.host.shows(self)

    def eval(self, js: str):
        if self.shown():
            self.host.web.eval(js)

    def entered(self):
        """The tab was just drawn."""

    def left(self):
        """Another tab was chosen or the window closed."""

    def on_bridge(self, message: str):
        prefix, _, rest = message.partition(":")
        if prefix == self.PREFIX:
            command, _, arg = rest.partition(":")
            self._on_message(command, arg)

    def _on_message(self, command: str, arg: str):
        pass
