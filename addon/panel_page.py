"""The page inside the side chat panel (review window and Add Cards window). Display only."""

import html

_PANEL_HTML = """
<style>
html, body { height: 100%; margin: 0; }
body { display: flex; flex-direction: column; box-sizing: border-box; padding: 0.5em 0.7em; font-size: 14px; text-align: left; }
#hd { display: flex; align-items: center; justify-content: space-between; font-weight: 700; margin-bottom: 0.4em; }
#clr { font: inherit; font-size: 12px; font-weight: 400; margin-right: 6px; padding: 1px 8px; cursor: pointer; }
#x { cursor: pointer; opacity: 0.6; font-size: 20px; line-height: 1; padding: 0 4px; user-select: none; }
#x:hover { opacity: 1; }
#log { flex: 1; overflow-y: auto; min-height: 0; }
#log .hint { opacity: 0.6; margin-top: 0.4em; }
#log .you, #log .ai, #log .wait { padding-left: 1.2em; text-indent: -1.2em; white-space: pre-wrap; }  /* hanging prefix */
#log .you { margin-top: 0.7em; font-weight: 600; }
#log .you::before { content: "> "; }
#log .ai, #log .wait { margin: 0.2em 0 0; }
#log .ai::before, #log .wait::before { content: "● "; }
#log .ai.err { color: #d33; }
#log .wait { opacity: 0.6; }
#quote { display: none; position: relative; margin-top: 0.5em; padding: 0.35em 1.6em 0.35em 0.6em; border-left: 3px solid #2563eb;
         border-radius: 4px; background: #2563eb1a; font-size: 0.92em; max-height: 6.5em; overflow-y: auto; white-space: pre-wrap; }
#quote .lbl { display: block; font-size: 0.8em; font-weight: 700; color: #2563eb; margin-bottom: 0.1em; }
#quote .rm { position: absolute; top: 2px; right: 6px; cursor: pointer; opacity: 0.6; font-size: 16px; }
#quote .rm:hover { opacity: 1; }
#log .q { margin: 0.2em 0 0 0.8em; padding-left: 0.5em; border-left: 3px solid #2563eb; opacity: 0.75; font-size: 0.92em;
          white-space: pre-wrap; max-height: 5em; overflow: hidden; }
#quick { margin-top: 0.5em; }
#quick button { font: inherit; font-size: 12px; padding: 1px 10px; cursor: pointer; }
#cmd { width: 100%; box-sizing: border-box; margin-top: 0.5em; padding: 0.5em; font: inherit; border-radius: 6px; resize: none;
       border: 1px solid #8888; background: transparent; color: inherit; }
</style>
<div id="hd"><span>AI Study</span><span><button id="clr" title="Clear the chat">Clear</button><span id="x" title="Close">&times;</span></span></div>
<div id="log"><div class="hint">__HINT__</div></div>
<div id="quote"><span class="lbl">HIGHLIGHTED</span><span id="qtext"></span><span class="rm" title="Remove">&times;</span></div>
<div id="quick"><button id="explain" title="Explain the highlighted text (or the card)">Explain</button> <button id="doit" title="Make the change the AI just suggested">Do it</button></div>
<textarea id="cmd" rows="3" placeholder="Type your question (Enter to send, Shift+Enter for a new line)"></textarea>
<script>
(function () {
  const log = document.getElementById("log"), cmd = document.getElementById("cmd");
  const hint = log.querySelector(".hint").cloneNode(true);
  const quoteEl = document.getElementById("quote"), qtext = document.getElementById("qtext");
  let sel = "", busy = false, wait = null, stale = 0;  // stale: replies still to come for messages that were cleared
  const typeset = el => { if (window.MathJax && MathJax.typesetPromise) MathJax.typesetPromise([el]).catch(() => {}); };
  function add(cls, html, text) {
    const d = document.createElement("div"); d.className = cls;
    if (html !== null) d.innerHTML = html; else d.textContent = text;
    const h = log.querySelector(".hint"); if (h) h.remove();
    log.appendChild(d); log.scrollTop = log.scrollHeight; return d;
  }
  function setQuote(s) { sel = s; qtext.textContent = s; quoteEl.style.display = s ? "block" : "none"; }
  function clearAll() {
    if (busy) stale++;
    log.innerHTML = '<div class="hint">' + hint.innerHTML + "</div>"; cmd.value = ""; setQuote(""); busy = false; wait = null;
  }
  document.getElementById("clr").addEventListener("click", () => { clearAll(); cmd.focus(); });
  document.getElementById("x").addEventListener("click", () => pycmd("hide"));
  quoteEl.querySelector(".rm").addEventListener("click", () => { setQuote(""); cmd.focus(); });
  function send(text) {
    if (busy || !text.trim()) return;
    if (sel) add("q", null, sel);
    add("you", null, text.trim());
    pycmd("send:" + JSON.stringify({sel: sel, text: text}));
    cmd.value = ""; setQuote(""); busy = true;
    wait = add("wait", null, "Thinking…");
  }
  cmd.addEventListener("keydown", function (e) {
    e.stopPropagation();  // Anki's shortcuts must not fire while typing
    if (e.key !== "Enter" || e.shiftKey || e.isComposing) return;
    e.preventDefault();
    send(cmd.value);
  });
  document.getElementById("explain").addEventListener("click", () => { send("Explain this."); cmd.focus(); });
  document.getElementById("doit").addEventListener("click", () => { send("Do it: make the change you just suggested."); cmd.focus(); });
  window.aiPanel = {
    quote(s) { setQuote(s); cmd.focus(); },  // a new highlight replaces the previous one
    reply(html, err) {
      if (stale) { stale--; return; }
      if (wait) { wait.remove(); wait = null; }
      busy = false;
      typeset(add("ai" + (err ? " err" : ""), html));
      cmd.focus();
    },
    clear() { clearAll(); stale = 0; },
  };
})();
</script>
"""


def panel_html(hint: str) -> str:
    """The side panel's page; `hint` is the grey line shown while the conversation is empty."""
    return _PANEL_HTML.replace("__HINT__", html.escape(hint))
