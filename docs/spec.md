# AI Quizzer add-on for Anki — spec

How the add-on works **now**. Version history is in [CHANGELOG.md](../CHANGELOG.md); the user guide is [guide.md](guide.md). When behaviour changes, update the section here and add a changelog entry.

Built and tested on macOS, Anki 26.9.2; also installed on Windows.

## Goal

Run an AI study loop inside the Anki desktop reviewer: the AI turns each card into rewritten questions, the user types free-text answers, the AI grades them and recommends an ease, and the user still presses Anki's own Again / Hard / Good / Easy. The add-on never calls the scheduler.

## Layout

| Module | Role | Imports Anki? |
|---|---|---|
| `__init__.py` | Loads `main.py` only inside Anki | guarded |
| `main.py` | Hooks, AI Study toggle, reviewer glue, what each window's chat sees (`reviewer_context`, `browse_context`, `add_cards_context`) | yes |
| `ui.py`, `panel_page.py` | Reviewer HTML/JS; the side chat panel's page | no |
| `side_panel.py` | The chat panel: docked in the AI Window and the main, Browse and Add Cards windows | yes |
| `ai_window.py` | 🤖 AI Window: tabs on the left, the chat docked on the right | yes |
| `assistant.py` | The AI chat (`Conversation`, one per window): sections, rounds, applying changes, note search | yes |
| `assistant_ops.py` | The chat's system prompt, message and reply parsing | no |
| `tab_page.py` | `Tab` base for the AI Window's tabs (bridge routing, shown / eval); `load_config` / `save_config`, `deck_ids` | yes |
| `synced.py` | Which settings sync with the collection and where they live in it; load, save, one-time migration (takes a `Collection`) | no |
| `config_page.py`, `generate_page.py` | ⚙ Settings and ✨ Generate/Update tabs | yes |
| `session.py` | Provider CLIs: find, isolate, run, parse; login; model lookup | no |
| `textutil.py` | Shared text helpers: style guide, HTML to text, JSON reply parsing, safe rich text | no |
| `grading.py` | Tutor prompts and reply parsing | no |
| `note_chat.py` | The chat's NOTE section (reviewer, Browse, Add Cards), field-edit planning, search results | no |
| `missed.py` | The Missed section of a note | no |
| `missed_today.py`, `missed_page.py` | 📋 Today's Missed: notes whose Missed section carries today's date (collection query / read-only tab) | no / yes |
| `config_ops.py` | The chat's SETTINGS section, validated config changes, toggles | no |
| `generate_ops.py` | The chat's CARDS section, reference reading, change validation | no |
| `generate_col.py` | AI-GEN staging ops on a `Collection` passed in | no |
| `errorlog.py` | Copies tracebacks that went through the add-on to `user_files/error.log` (`install()` in `main.setup` wraps `sys.excepthook` and `threading.excepthook`; Anki still handles the error as before; the file starts over past 200 KB) | no |
| `health.py` | Self-check, error classification, reviewer failure policy, update / rollback | no |
| `fixes.py` | Fix buttons in the Settings tab's messages; talks to the tab only through `cfg`, `provider`, `apply`, `login`, `say`, `refresh` | yes |
| `state.py` | What the add-on learns about the CLIs: real model names, `last_good` versions. `user_files/state.json`, kept by Anki across updates; never in the config or its undo history | no |
| `style.md` | Formatting guide (bold, note-field HTML, LaTeX) appended to the tutor and chat system prompts | — |
| `config.json` | Shipped defaults (this computer's settings live in the gitignored `meta.json`; synced ones in the collection, see Synced settings) | — |

Everything that doesn't import `aqt` is unit-tested with plain pytest.

## Providers and sessions (`session.py`)

- `provider`: `claude` (default) or `codex`. Uses the user's logged-in CLI; no API keys. CLI paths `claude_path` / `codex_path` are auto-detected when empty, including when Anki is launched from the Dock (no shell `PATH`).
- **Windows**: every CLI call uses UTF-8 pipes and, on Windows, no console window (`session.PROC_KW`). The Claude system prompt is passed as a file (`--system-prompt-file`, written into the session's temp folder by `session.system_prompt_file`), never as an argument: npm installs `claude.cmd`, and `cmd.exe` cuts arguments at the first newline. The test suite runs on Windows, macOS and Linux in GitHub Actions (`.github/workflows/tests.yml`), using `.cmd` wrappers for the fake CLIs on Windows. Rollback needs the Mac/Linux install layout; elsewhere it offers no versions.
- **Stateless requests**: every prompt carries the card, questions, answers, deck prompts and the card's last Missed section. No conversation memory is relied on.
- **Claude**: grading runs one long-running `claude -p --input-format stream-json --output-format stream-json --verbose` per review session, kept only to skip startup. Starts on first request; stops when review ends, after a settings change, on profile close and on app exit. Each chat runs its own one of the same command, with the web tools, kept for its memory (see The AI chat).
- **Codex**: one `codex exec --json … -` per message, system prompt prepended on stdin; answer = last `agent_message` event.
- **Isolation** (both run in an empty temp directory with no user settings, hooks, plugins, MCP servers or tools):
  - Claude: `--safe-mode --setting-sources "" --strict-mcp-config --tools "" --disable-slash-commands --no-session-persistence`. `--bare` is not usable: it can't use subscription login.
  - Codex: `--ephemeral --ignore-user-config --ignore-rules --skip-git-repo-check -s read-only --disable shell_tool|apps|browser_use|computer_use|plugins -c web_search="disabled"`.
  - The chat alone (`web=True` in `make_backend` / `build_command` / `build_codex_command`) may search and read the web, and nothing more: Claude gets `--tools WebSearch,WebFetch --allowedTools WebSearch,WebFetch` (pre-approved: nobody can answer a permission prompt), Codex `-c web_search="live"`. Grading and question rewrites never get them.
- API: `request(card_id, prompt, parse, timeout, callback)` — callbacks on the main thread; the "ask" and "grade" prompts come from `grading.py`. One request in flight, later ones queue. Replies are tagged with their card id; replies for a card no longer shown are dropped.
- **Models**: `models: {claude, codex}`; `""` = the CLI's default. Settings always shows the real model id, read from the CLI's own output (Claude's stream-json `init` event, Codex's stderr `model:` header), saved by `session.remember_model` into `state.py` the moment a probe or real call reports it (rendering never writes). The two keys older versions kept in the config (`resolved_models`, `last_good`) are dropped on the next settings change.
- **Login**: Claude `claude auth status|login|logout`; Codex `codex login status` / `codex login` / `codex logout`. On Windows, login runs in its own console window (`CREATE_NEW_CONSOLE`, no captured output): the CLI may print a sign-in link and wait for a pasted code, which a hidden process can neither show nor receive. Elsewhere it runs hidden and the CLI opens the browser.

## Reviewer flow (`main.py`, `ui.py`, `grading.py`)

Only active while **AI Study** is ON, and only for cards whose home deck has AI Study on (per-deck setting, default on; see Deck Settings in Settings). The ON/OFF link is on the home screen, on the deck overview and in **Tools → AI Study mode**. It stays as the user last left it across Anki restarts (`state.json` → `ui.ai_study`; off on first install). Off means the plain reviewer runs and no AI process starts; turning it off kills the session. The flow is display-only, through `gui_hooks.card_will_show`: nothing is written to the card except the Missed section.

**Question side**
- Rewrite question is on by default and set per deck (see Deck Settings in Settings). When on for the card's home deck, an ask request carries only the card's front (question) and deck rules, never the back — except, when a deck rule mentions misses (`grading.wants_missed`), the points of the card's Missed section with their counts, for what the rules ask (e.g. hints), never as questions — and returns `{"questions": [1–4], "hints": [...]}`, one question per distinct point the card bundles (at most 4 by default; deck rules override the defaults, up to 8 questions). `"show_original": true` opens **Show original** above the questions, e.g. when a deck rule says to present the card's question as written. A question that asks for several parts comes as `{"question": stem, "parts": [...]}` and its hint as a list, one per part. The add-on numbers questions `1.`, `2.` (only when there are several) and parts `3.1`, `3.2` (or `1.`, `2.` under a single question). Each hint (short, never the answer) shows as a **?** tooltip on the smallest unit: after each part, or after the question when it has no parts. Missing hints are allowed. A question with parts still has one answer box; the prompt says so, so "a box per section" deck rules come back as separate questions. When deck rules name the questions or sections, each question is that name exactly as written and any guidance for it goes in its hint. `parse_questions` returns plain-text `questions` (parts as numbered lines, used by the grade and edit prompts and the verdict, which numbers its rows the same way) and `items` for the question side. Otherwise the card's own question is used.
- Rewrite question off, but a deck prompt applies (own or inherited): the ask request still runs (`config_ops.ask_mode` → "keep"). The card's question shows as written, with no Show original fold, and no box until the reply arrives. The AI is told not to repeat or rephrase it and to return only what the deck rules add on the question side, or `"questions": []`. `parse_added_questions` accepts an empty list, and `setQuestions([])` then gives one plain box. That way deck prompts shape the question side (sections, box count, show original) as well as grading. The Settings panel notes this next to the switch. With no deck prompt and the switch off, there is no ask request.
- Cloze cards always use their own blanked question.
- Layout: a collapsed **Show original** (Anki's normal question) at the top, then a question + answer box pair for each question. With rewritten questions, no box is shown until `ask` returns (only "Thinking of a rewritten question…"). If `ask` fails, one box appears under the opened original. Without rewritten questions (or for cloze), the original is shown with its box ready at once.
- **Enter** is a plain newline in the boxes (it never grades). Anki's shortcuts don't fire while typing. **Ctrl/Cmd+Enter** in a box and the **Show Answer** button (`Reviewer._showAnswer`, wrapped by `main.around_show_answer`, which asks the page via `aiStudy.submitNow()`) are the only ways to grade: they grade if any box has text, otherwise just show the answer. Anki's Space/Enter keys (`Reviewer.onEnterKey`, wrapped by `main.around_enter_key`, which sets `S.key_reveal`) never grade; they only show the answer. Unanswered boxes among filled ones are sent as "(blank)". With no boxes yet (`ask` pending), or after a failed grading, Space shows the answer. Cards with AI Study off keep Anki's behaviour.

**Answer side**
- A grade request returns `{"verdict": "wrong"|"partial"|"correct", "ease": 1-4, "feedback", "missed": [str], "per_question": [...]}`.
- The full card is sent again, so grading works even if `ask` failed or was skipped.
- A question left blank is marked **skipped**, not wrong: it doesn't lower the verdict or ease, which judge the answered questions. The rubric is fixed: wrong 1, partial 2, correct 3, correct + complete and crisp 4. Missed bullets are short (the prompt caps hints, notes, whys and Missed items at about 15 words) and contain only reference facts the user left out.
- The verdict (badge, the user's answer, feedback, per-question marks, Missed bullets) is inserted just below the front of the card, right after `<hr id=answer>` (Anki scrolls it to the top), above the normal answer. Each `per_question` item carries `parts`: the user's answer clipped into claims in their own words, each with a verdict and, unless correct, a `why`. Colour follows verdict (green / orange / red); without parts the whole answer is coloured by its grade. Verdicts agree upward: a question is no better than its weakest claim, the card no better than its weakest question. The recommended ease button is outlined; the user presses a button themselves.

**Highlight to ask** (both sides, whenever AI Study is on for the card)
- Selecting card text shows a small **AI** bubble at the highlight (`ui.ask_html`). Selections that start inside an answer box are editing, not asking. Clicking the bubble opens the side panel and shows the highlight as a quote above the chat box; the full highlight is what the AI receives, and the quote stays above the message it was sent with.
- The panel (`side_panel.ReviewPanel`) is docked on the right of the main window, which widens by the panel's width so the card keeps its size and position when the panel opens; the user can drag the divider between the card and the panel to resize it, and closing shrinks the window by the panel's current width (it slides left first if it would leave the screen; a maximized window can't grow, so the card area gives way). × closes it and shrinks the window back. An **Explain** button above the chat box sends "Explain this." with the current highlight in one click; **Simpler** sends "Explain this in simpler, less technical words; use an everyday example if it helps." the same way (it uses the highlight if there is one); **Do it** sends "Do it: make the change you just suggested." (the AI remembers its suggestion). **Clear** empties the conversation and stops the chat's CLI, so the AI forgets it too.
- The conversation survives card changes and the end of the review session (the panel closes then; reopening shows it again). It ends with **Clear** or when the profile closes. One message is answered at a time; replies for cleared messages are dropped. Your messages start with `> `, replies with `● ` (same in every chat panel).
- It is the AI chat (see The AI chat) with the NOTE section loaded; "this deck" is the card's home deck. Its failures don't count toward the study failure policy.
- Question side (`note_chat.question_side_context`): only the card's question and the questions shown, never the answer, which the AI must not give away even when a deck it reads, a search or the web shows it; the note is never edited.
- Answer side (`note_chat.answer_side_context`): the note's raw fields, the grade when graded, deck rules and the highlight. Questions are answered without changes; change requests edit the note; one message can do both. Only existing fields that differ are written, as one undo step. The save names the reviewer as initiator, so Anki doesn't refresh it (its redraw focuses the card, and an edit that adds a card, such as a new cloze or Add Reverse, makes it jump to the next card); `main.redraw_edited` then redraws the card itself, if it is still on screen, and puts the keyboard back in the chat box when it was there.

**AI panel in the Add Cards window** (only while AI Study is on)
- **Browse window** (`gui_hooks.browser_will_show`, only while AI Study is on): the same docked panel as the reviewer (`side_panel.ReviewPanel`, built with the Browse window) sits on the window's right edge as part of it: opening widens the window by the panel's width, closing shrinks it back, and the user can drag the panel's edge to resize it. It is opened from the **AI Study → Chat about this note** menu or by the **AI** bubble (`side_panel.SelectionBubble`: after a mouse release in the editor, if the web view's `selectedText()` is non-empty, a small button appears at the mouse; clicking it opens the panel with the selection quoted). The editor is saved first (`call_after_note_saved`), then the chat gets `note_chat.answer_side_context` for the open note with the card's deck rules (if one card is open; AI Study off for its deck refuses). Replies are applied by `apply_note_edit`, shared with the reviewer's answer side: only existing fields that differ are written, as one undo step.
- An **AI Study** button on the Add Cards window (`gui_hooks.add_cards_did_init`) toggles the same docked panel (`side_panel.ReviewPanel`; the Add Cards window is a `QMainWindow`, so it docks like Browse's: part of the window, resizable, widens the window). It is the same chat as highlight-to-ask, with no highlight quote.
- NOTE section: the fields typed so far (saved first) and the selected deck's rules (`note_chat.new_note_context`). The AI may fill in or change fields: `apply_new_note_edit` writes the changes that name existing fields and differ into the editor's live note (`editor.note`, then `editor.loadNote()`). Nothing is saved to the collection and there is no undo step; the user adds the note as usual.
- Searching the user's other notes ("is this a duplicate?", "match my other cards") is the chat's Anki search (see The AI chat).
- The Browser editor has no panel yet.

**Missed section** (`missed_append`, default on; `missed.py`)
- The note keeps one `<hr><b>Missed (date)</b> <i>N reviews</i><ul><li><b>[K]</b> point</li>…</ul>`: the latest review's date, the number of graded reviews, and per point how many of them missed it. Points missed often are marked in red (`missed.RED_FROM`).
- **📋 Today's Missed** (a tab of the AI Window; `missed_today.py`, `missed_page.py`): searches the collection for `"Missed (<today>)"`, keeps notes whose stamp equals today's local date (the same clock that writes it, so Anki's 4am rollover isn't used) and that have points, and lists them by deck, most-missed note first. A note reviewed again on a later day moves to that day. Read-only.
- Each review adds one to the points missed again and adds new ones; the others keep their count. Points are matched by normalized words, not exact text, so rewording doesn't start a second counter. Most-missed first; capped (`missed.MAX_MISSED`). Older formats are still read.
- It goes into the first existing field of `Back` → `Back Extra` → the note's last field. The tutor prompt treats it as past gaps, not required content, and asks for repeats in the listed point's own words.
- A write failure shows a note in the verdict; the review is unaffected.

**Formatting** (`style.md`, `textutil.rich`)
- `style.md` is the only place formatting rules live. It is appended to every system prompt (tutor, chat), so all providers follow one guide.
- Short texts are shown through `textutil.rich` (HTML-escaped, then `**x**` → `<b>`); the same goes for Missed bullets saved into the note.
- Note-field colour (only in note HTML the AI writes or edits, never in short texts): colour marks what must be *recalled*, judged against the deck's study goal (from its deck rules, name and neighbouring notes). Blue `#3b82f6` = the core concept / decision, amber `#d97706` = the why (trade-off, pitfall, exception), purple `#a855f7` = anchors (numbers, names, formulas). Every section gets its core point: about one 1–6-word span per 40–60 words in long notes, at most a fifth of the text; never red or green (reserved for grading feedback); existing colours are kept. Deck rules still outrank it. Generate sends the user's deck rules (all decks that have one) in its prompt and starts its reply with `Goal: …` when it colours, so a wrong guess of the goal is visible.
- Math is LaTeX in `\( \)` / `\[ \]`. Anki typesets the card once; later-arriving text is typeset on arrival.
- `textutil.parse_json_reply` repairs the usual LaTeX slips in JSON (single backslashes). A single-backslash `\neq` can't be told from a newline and stays broken.

**Prompt context**: rendered question and answer as plain text (no images); the ask request gets the question only, grading gets both. Custom Generic Rules go in the system prompt; each card sends its own home deck's prompt chain (`card.odid or card.did`, root → leaf, inner wins). Priority, highest first: deck rules, Generic Rules, then the built-in tutor defaults and `style.md`; only the JSON reply format is fixed. The chat's NOTE rules give deck rules the same top priority. Deck rules reach both the question side and grading, whatever the Rewrite question switch says.

## 🤖 AI Window (`ai_window.py`)

A window of its own (a `QMainWindow`, like Browse), so it can stay open while reviewing. Opened from **🤖 AI Window** on the home screen and the deck overview (next to the AI Study ON/OFF link) and from **Tools → AI Window**; it works whether AI Study is on or off.

- Tabs on the left: **⚙ Settings**, **✨ Generate/Update**, **📋 Today's Missed** (`tab_page.Tab` subclasses; one web view, redrawn on a tab change). Every tab uses the same full-width layout and the page scrollbar always takes its room, so switching tabs doesn't shift anything.
- The AI chat is docked on the right and always open (`side_panel.ReviewPanel` without × and without the Explain / Simpler / Do it buttons); the window is widened by its width when first shown.
- Highlighting text in a tab shows the **AI** bubble (`side_panel.SelectionBubble`, as in Browse); clicking it quotes the text in the chat.
- Closing the window keeps the conversation for the next open; a message still being answered (a batch run, say) finishes and its cards are staged.
- Closing the profile closes the window.

## The AI chat (`assistant.py`, `assistant_ops.py`)

One chat for everything, in a side panel of each window: the AI Window, the reviewer (highlight-to-ask), Browse and Add Cards. Each window has its own `Conversation`. Like a general assistant it answers anything; it can also change settings, make and update cards and edit the open note, and it may search and read the web (see Isolation).

- **Sections**: `settings` (config_ops `SETTINGS_RULES` / `settings_context`), `cards` (generate_ops `CARDS_RULES` / `cards_context`), `missed` (today's Missed points, read-only; `assistant_ops.missed_context`), `note` (note_chat `NOTE_RULES` and the open note; only where one is open). The window decides which are loaded at first:

  | Where | Loaded | "This deck" |
  |---|---|---|
  | AI Window, any tab | settings, cards, missed (full access) | the deck selected in the Settings tree |
  | Reviewer, Browse, Add Cards | note | the card's home deck / the chosen deck |

- **Need**: when a request needs another section the AI replies `{"need": [...]}` and gets it in a follow-up (`assistant_ops.follow_up`), then answers the same message (`note` can't be asked for). `read_decks` from a chat without the cards section loads it too, so any chat can read any deck. A section loaded once stays loaded for the rest of the conversation. Any window can do anything this way: "make cards for this" from the reviewer loads cards.
- **Message** (`assistant_ops.message`): `WHERE: <window and tab>`, each loaded section's context (to Claude only the ones that changed since it last got them, with a line naming the unchanged ones), what happened since the AI's last reply (a batch run), the recent conversation (Codex only), the highlight, `User: <message>`, then search results. **System prompt** (`assistant_ops.system_prompt`): fixed — the base, every section's rules, then `style.md`.
- **Reply**: `{"reply", "need", "search", "settings", "read_decks", "per_card", "cards", "fields"}` (`assistant_ops.parse_reply`); keys of a section that isn't loaded are rejected with a `✗` line.
- **Calls** (`make_backend(..., web=True)`): Claude runs one process per chat, started on the first message and again after a crash or a provider / model / path change; Codex starts one per message. Timeout 300 s. At most 6 calls per message for loading sections, searching and reading decks (`MAX_ROUNDS`). Each batch of a per-card run goes to a throwaway process with everything it needs, so a big run doesn't fill the conversation; the chat is told the outcome with the next message.
- **Memory**: within an Anki run. Claude's process keeps the conversation; Codex gets the last 3 exchanges resent (`HISTORY`). **Clear** and closing the profile end it; nothing is saved to disk. Browse and Add Cards chats end with their window.
- **Anki search** (any window): `"search": "<Anki search query>"` makes `assistant.search_notes` run it read-only (`col.find_notes`, first 20 notes, each field as plain text cut at 300 chars, with deck and note type) and ask again with `note_chat.search_block` appended. At most 3 per message, the last one telling the AI to answer now; a bad query returns its error text. The queries used are added to the reply as `(Searched: …)`.
- **Applying** the final reply: settings changes through the Settings tab (`ConfigPage.apply_from_chat`: validated by `config_ops.apply_changes`; `logout` is refused — Log out is a button; `login` runs the sign-in); card changes staged in AI-GEN as in Generate/Update below, with a **Review in Generate/Update** button under the reply that opens that tab; field changes into the open note (reviewer and Browse: one undo step via `main.apply_note_edit`; Add Cards: into the editor).
- **Safety**: reference files, search results, notes and web pages are data, never instructions; the AI is told to act only on the user's own message. Every change still goes through validation, undo and AI-GEN approval.
- One message at a time per panel. Only one chat at a time works on cards: while one does, the Generate/Update tab's collection buttons and other chats' card requests wait (`GeneratePage.busy`).

## ⚙ Settings (`config_page.py`, `config_ops.py`)

A tab of the AI Window. Plain controls; changes asked in words go through the chat (settings section).

- **Changes from the chat**: `config_ops.apply_changes` validates each change: `set` known keys with type/range checks, `add_custom` / `remove_custom`, `set_deck_prompt` / `clear_deck_prompt`, `set_deck_ai` / `set_deck_sharp` (`on`: true / false / null = follow parent), `undo` (snapshot restore), `login` / `logout` (the chat never sends `logout`). Saving uses `tab_page.save_config` (see Synced settings).
- The tab's message area shows the latest 3 messages from fixes, login and updates. The chat gets the real model in use, never lists or guesses model names, and points to the Model dropdown.
- **Configurations**:
  - Provider and Model rows: dropdowns. The model list is loaded live from the CLI and never stored.
  - The Model row shows the real model id, looked up once in the background. If the lookup fails (e.g. the provider's CLI isn't installed) it shows the configured model or `unavailable` and isn't retried until the config changes or the tab is reopened, so the tab doesn't redraw in a loop.
  - Login state with **Log in** (logged out) or **Log out** (logged in), timeouts, and the CLI version with **Update**.
  - **Missed append**: On/Off toggle. `config_ops.TOGGLES` is the single source for each toggle's label and help text. Clicks go through `apply_changes`. Each toggle has a CSS **?** help bubble.
  - Plain controls always work, even when the provider's AI is broken.
- **Custom Generic Rules**: numbered rules, applied to every card.
- **Deck Settings**:
  - Clicking a deck starts the chat box on the right with `Deck prompt for "<deck>": ` and focuses it, opening the chat if it was hidden (`config_ops.deck_prefix`, `aiPanel.prefill`). `SETTINGS_RULES` tells the AI that such a message always sets that deck's prompt in the user's own wording, worked into the existing prompt (replaced only when the user says so; nothing they asked for is dropped), and that the reply quotes the prompt set. Clicking another deck swaps the prefix and keeps anything typed after it. Clicking the selected deck again deselects it: its folder closes and the prefix is removed (text typed after it stays). The tree lists decks as Anki's deck list does, so an empty Default deck is hidden (`all_names_and_ids(skip_empty_default=True)`). A message the user wrote themselves is never replaced.
  - The real deck tree, with ● marking decks that have a prompt.
  - Selecting a deck shows its panel directly under it in the tree (a selected parent expands): its own prompt, the ones it inherits, and the deck toggles with which deck decides each.
  - Deck toggles (`config_ops.DECK_TOGGLES`): **AI Study** (`deck_ai`; off = plain reviewer for that deck's cards) and **Rewrite question** (`deck_sharp`), each `{deck_id: bool}`. The innermost deck on the path with a setting wins; none = on. Each panel On/Off button flips the selected deck's effective value. Setting a deck (button or chat) drops its subdecks' own settings, so they follow it at once. A subdeck set afterwards stays as an exception until one of its ancestors is set again. Updates keep the page's scroll position. A deck prompt can't switch them: the decision is made before any AI call, so the chat uses `set_deck_sharp`. The old global `sharp_questions` key is dropped on the next settings change.
  - In the config these are `deck_prompts: {deck_id: prompt}`, `deck_ai`, `deck_sharp`; they are stored on the decks themselves (see Synced settings), so they survive deck renames and go away with a deleted deck.
  - Deck names resolve exact → case-insensitive → unique leaf name; anything else is rejected.
- Changes apply to the next AI call (`main.on_config_changed`): the grading CLI restarts with them and AI turned off by failures gets another try, while the card on screen keeps its questions and grade.

## Synced settings (`synced.py`, `tab_page.load_config` / `save_config`)

Anki sync carries the collection, never add-on files, so settings that should follow the user live in the collection. The rest of the add-on sees one config dict with the same keys as before.

| Settings | Stored in | How Anki sync merges it |
|---|---|---|
| Deck prompt, AI Study, Rewrite question | each deck object, key `anki_ai`: `{"prompt", "ai", "sharp"}` (only the ones set) | per deck: the newer deck wins, so edits to different decks on different devices both survive |
| `custom`, `missed_append`, `ask_timeout_s`, `grade_timeout_s` | collection config `anki_ai` | the whole config table comes from the side whose collection changed last; an unsynced edit can lose to the other device |
| `provider`, `models`, `claude_path`, `codex_path` | `meta.json` | not synced: they depend on the computer |

- `save_config` writes `meta.json` (device keys) and only the parts of the collection that changed since the config it started from: an unchanged deck keeps its modification time so it doesn't win a later sync by accident, and only the general settings that changed are written into `anki_ai` (so a fresh computer's defaults never land there).
- Migration, once per profile per computer (`state.json` → `synced`): settings the user saved in `meta.json` (never `config.json` defaults) are merged in. What another device already synced wins where both set the same thing (it was set after this computer's old settings); everything else is added: missing general settings, custom rules not already there (appended), and deck fields a deck doesn't carry yet. With auto sync on (`mw.can_auto_sync()`), migration waits for the first `sync_did_finish`, so the other device's settings are there to merge with; writing before that sync would make this collection the newer one and its config would replace theirs. The old keys stay in `meta.json` unread, for other profiles.
- A deck setting change is a normal Anki undo step ("Update Deck"); earlier undo history is kept. General settings are written without an undo step.
- After a sync (`sync_did_finish`), a pending migration runs and an open Settings tab redraws. Everything else reads the collection on use.

## ✨ Generate/Update Cards (`generate_page.py`, `generate_ops.py`, `generate_col.py`)

A tab of the AI Window. Card requests are made in the chat (cards section) from any window; this tab holds the reference, the progress of a running request and the staged cards to review.

- **References**:
  - Chosen with **Choose folder…** / **Choose file…** (native pickers opening on the Desktop) or cleared with **×**. The path box is read-only.
  - Must resolve to something strictly inside the Desktop: `~/Desktop`, or on Windows the folder the shell reports (OneDrive often moves it to `~/OneDrive/Desktop`; `generate_ops.desktop`).
  - Text files only. Binary and non-UTF-8 files are listed as skipped. Hidden files, `.git`, `node_modules`, `__pycache__` and venvs are ignored.
  - Limits: ≤ 300 files and ≤ 150k characters per message; anything cut off is reported.
  - Re-read on every chat message that has the cards section loaded, from whichever window.
- **Batches**: the AI sets `per_card: true` with `read_decks` when the request changes each existing card individually. If the read decks hold more than `BATCH_SIZE` (10) cards, the add-on resends the request once per batch (`generate_ops.chunk_notes`, each card once) with a `BATCH i of n` line that limits the AI to the listed cards. Each batch's changes are applied (one undo step) and shown before the next batch starts; the status reads `Batch i of n — k of N cards done`, the staged list says it is still working, and Submit / Approve all are disabled. **Stop after this batch** (or an error) ends the run with what is staged and a summary of how many cards were processed. The chat panel shows the same progress in its waiting line, and its history gets one entry for the whole run.
- Cards the AI read (`read_decks`) are kept while the tab is on screen and forgotten after a request made elsewhere, so the AI re-reads them when next needed.
- **Updating existing cards**:
  - The AI may return `read_decks`. The add-on then loads those decks' notes (subdecks included, raw field HTML, ≤ 120k chars) and resends the request, for at most 2 rounds.
  - `update {note_id, fields}` stages a copy tagged `ai_generate_of_<nid>`; a second update edits that copy.
- **AI-GEN staging deck**:
  - A temporary top-level deck, created when first needed. Its subdecks mirror real deck paths.
  - New cards are Basic or Cloze. They may target any deck path, including a new top-level deck; only `AI-GEN` itself is never a target.
  - Staged cards carry the `ai_generate` tag. State lives in the collection, so staged cards survive restarts and can be edited in the Browser.
- **Approve → Submit**:
  - **Approve / Unapprove** (card, deck or all) toggles the `ai_generate_ok` tag. An AI edit of an approved card clears its approval, and the AI is told to leave approved cards alone unless asked.
  - **Submit N approved**:
    - Updates are written into the originals, keeping review history; if the original was deleted, the update is kept as a new card.
    - New cards move to their real deck, which is created if missing, with the tag removed.
    - Emptied AI-GEN decks are removed.
  - **Discard** deletes the card or deck immediately.
- **Show Original / Show Update** on UPDATE cards: client-side, and the choice survives redraws.
- **Undo**: every action, including each AI change batch, is one undo step (`add_custom_undo_entry` + `merge_undo_entries` in a `CollectionOp`). Actions use a few batched ops, because Anki keeps only ~30 undo steps. If a merge still fails, the saved changes are reported instead of an error.

## Errors, self-check, fixes (`health.py`, `fixes.py`)

A failure never blocks review: after a failed grading, Space shows the answer.

| Failure | Shown | Behaviour |
|---|---|---|
| CLI missing / not logged in / crash / other error | "AI error: <message> — open 🤖 AI Window → ⚙ Settings to fix it." | crashed process respawns on next call; 2nd failure → "AI unavailable: <message>", AI off until the reviewer is reopened |
| Usage limit | "Usage limit: <message>" | AI off until the reviewer is reopened |
| Timeout (`ask_timeout_s` 30, `grade_timeout_s` 60) | "AI timed out." | late reply dropped |
| Non-JSON reply | — | one retry with "JSON only", then error |
| Missed write fails | red note in verdict | review unaffected |
| Anki closes mid-request | — | process killed, late callbacks ignored |

- **Self-check** (`health.self_check`):
  - Runs when the Settings tab opens and after update or rollback.
  - `session.startup_check` starts the real study command and stops before any answer, so a pass proves the CLI accepts every add-on flag. Claude: until its `init` event names the model. Codex: the command without `--json` until its header names the model, then the exact `--json` command until its first event. The chat's web-enabled command is started the same way.
  - A pass records `last_good[provider] = version` in `state.py` (the Roll back target).
- **Diagnosis**:
  - Reviewer errors are stored in `health.LAST_ERROR`.
  - "Usage limit" is decided by one rule, `session.error_kind`, which both the reviewer and Settings use.
  - The reviewer's failure policy is `health.study_failure` (pure, tested).
  - `health.classify` sorts them into incompatible | auth | limit | timeout | missing | other, which picks the fix buttons:
    - **Roll back to <last working>**
    - **Update**
    - **Log in**
    - **Allow more time** (×2, cap 600 s)
    - **Use <other provider>**
    - **Copy error report**
## Testing

- `pytest tests`: pure logic, plus `session.py` against `fake_claude.py` / `fake_codex.py`, which give no real AI calls and no plan usage. Covers lifecycle, queueing, stale drop, crash restart, timeout and bad JSON.
- `tests/test_generate_col.py` runs on a real temp collection with Anki's own Python and is skipped elsewhere.
- Manual acceptance in Anki: Basic card, cloze card, Space skip, Ctrl+Z, and no add-on CLI process left after leaving the reviewer.
