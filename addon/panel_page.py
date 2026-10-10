"""The page inside the side chat panel (AI Window, reviewer, Browse, Add Cards). Display only."""

import html

_PANEL_HTML = """
<style>
html, body { height: 100%; margin: 0; }
body { display: flex; flex-direction: column; box-sizing: border-box; padding: 0.5em 0.7em; font-size: 14px; text-align: left; }
#hd { display: flex; align-items: center; justify-content: space-between; font-weight: 700; margin-bottom: 0.4em; }
#stop { font: inherit; font-size: 12px; font-weight: 400; margin-right: 6px; padding: 1px 8px; cursor: pointer; display: none; }
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
#log .acts { text-indent: 0; margin-top: 0.3em; }
#log .acts button { font: inherit; font-size: 12px; padding: 1px 10px; margin-right: 0.4em; cursor: pointer; }
#cmd { width: 100%; box-sizing: border-box; margin-top: 0.5em; padding: 0.5em; font: inherit; border-radius: 6px; resize: none;
       border: 1px solid #8888; background: transparent; color: inherit; }
</style>
<div id="hd"><span>AI Study</span><span><button id="stop" title="Stop the answer being written; queued messages go on">Cancel</button><button id="clr" title="Clear the chat">Clear</button><span id="x" title="Close"__NOX__>&times;</span></span></div>
<div id="log"><div class="hint">__HINT__</div></div>
<div id="quote"><span class="lbl">HIGHLIGHTED</span><span id="qtext"></span><span class="rm" title="Remove">&times;</span></div>
<div id="quick"__NOQUICK__><button id="explain" title="Explain the highlighted text (or the card)">Explain</button> <button id="simpler" title="Explain in simpler, less technical terms, with an everyday example">Simpler</button> <button id="doit" title="Make the change the AI just suggested">Do it</button></div>
<textarea id="cmd" rows="3" placeholder="Type your question (Enter to send, Shift+Enter for a new line)"></textarea>
<script>
(function () {
  const log = document.getElementById("log"), cmd = document.getElementById("cmd");
  const hint = log.querySelector(".hint").cloneNode(true);
  const quoteEl = document.getElementById("quote"), qtext = document.getElementById("qtext");
  const stop = document.getElementById("stop");
  // Messages are answered one at a time, in order; the rest wait as "Queued". waits: message id -> its waiting line,
  // replaced by the reply. A reply for an id not in it (the chat was cleared meanwhile) is dropped.
  let sel = "", next = 0, waits = {};
  const pending = () => Object.keys(waits).length;
  const showStop = () => { stop.style.display = pending() ? "" : "none"; };
  const typeset = el => { if (window.MathJax && MathJax.typesetPromise) MathJax.typesetPromise([el]).catch(() => {}); };
  function add(cls, html, text) {
    const d = document.createElement("div"); d.className = cls;
    if (html !== null) d.innerHTML = html; else d.textContent = text;
    const h = log.querySelector(".hint"); if (h) h.remove();
    log.appendChild(d); log.scrollTop = log.scrollHeight; return d;
  }
  function setQuote(s) { sel = s; qtext.textContent = s; quoteEl.style.display = s ? "block" : "none"; }
  function clearAll() {
    log.innerHTML = '<div class="hint">' + hint.innerHTML + "</div>"; cmd.value = ""; setQuote(""); waits = {}; showStop();
  }
  document.getElementById("clr").addEventListener("click", () => { clearAll(); pycmd("clear"); cmd.focus(); });
  stop.addEventListener("click", () => { pycmd("cancel"); cmd.focus(); });
  document.getElementById("x").addEventListener("click", () => pycmd("hide"));
  quoteEl.querySelector(".rm").addEventListener("click", () => { setQuote(""); cmd.focus(); });
  function send(text) {
    if (!text.trim()) return;
    if (sel) add("q", null, sel);
    add("you", null, text.trim());
    const id = ++next;
    waits[id] = add("wait", null, pending() ? "Queued" : "Thinking…");
    pycmd("send:" + JSON.stringify({id: id, sel: sel, text: text}));
    cmd.value = ""; setQuote(""); showStop();
  }
  cmd.addEventListener("keydown", function (e) {
    e.stopPropagation();  // Anki's shortcuts must not fire while typing
    if (e.key !== "Enter" || e.shiftKey || e.isComposing) return;
    e.preventDefault();
    send(cmd.value);
  });
  document.getElementById("explain").addEventListener("click", () => { send("Explain this."); cmd.focus(); });
  document.getElementById("simpler").addEventListener("click", () => {
    send("Explain this in simpler, less technical words; use an everyday example if it helps."); cmd.focus();
  });
  document.getElementById("doit").addEventListener("click", () => { send("Do it: make the change you just suggested."); cmd.focus(); });
  window.aiPanel = {
    quote(s) { setQuote(s); cmd.focus(); },  // a new highlight replaces the previous one
    reply(id, html, err, actions) {  // id null: not about a message. actions: [[label, key]] -> buttons sending "act:<key>"
      const cls = "ai" + (err ? " err" : ""), wait = waits[id];
      let d;
      if (id === null) d = add(cls, html);
      else if (!wait) return;
      else {
        delete waits[id]; showStop();
        d = document.createElement("div"); d.className = cls; d.innerHTML = html;
        wait.replaceWith(d);  // right under its message, above any queued ones
        if (!pending()) log.scrollTop = log.scrollHeight;
      }
      if (actions && actions.length) {
        const row = document.createElement("div"); row.className = "acts";
        actions.forEach(([label, key]) => {
          const b = document.createElement("button"); b.textContent = label;
          b.addEventListener("click", () => pycmd("act:" + key)); row.appendChild(b);
        });
        d.appendChild(row);
      }
      typeset(d);
      cmd.focus();
    },
    status(id, text) { if (waits[id]) waits[id].textContent = text; },  // progress of a message being answered
    clear() { clearAll(); },
    prefill(prefix) {  // the Settings tab's deck click starts a message about it, unless the user typed their own
      const v = cmd.value;
      if (!v.trim()) cmd.value = prefix;
      else if (this.prefix && v.startsWith(this.prefix)) cmd.value = prefix + v.slice(this.prefix.length);
      else return;
      this.prefix = prefix;
      cmd.focus();
      cmd.setSelectionRange(cmd.value.length, cmd.value.length);
    },
    unprefill() {
      if (this.prefix && cmd.value.startsWith(this.prefix)) cmd.value = cmd.value.slice(this.prefix.length);
      this.prefix = null;
    },
  };
})();
</script>
"""


def panel_html(hint: str, quick: bool = True, closable: bool = True) -> str:
    """The side panel's page; `hint` is the grey line shown while the conversation is empty; quick: the Explain /
    Simpler / Do it buttons (about a card); closable: the × (the AI Window's chat is always open)."""
    hidden = ' style="display:none"'
    return (_PANEL_HTML.replace("__HINT__", html.escape(hint)).replace("__NOQUICK__", "" if quick else hidden)
            .replace("__NOX__", "" if closable else hidden))
