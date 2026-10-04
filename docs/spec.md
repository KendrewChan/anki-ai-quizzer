# AI Quizzer add-on for Anki — spec

How the add-on works **now**. Version history is in [CHANGELOG.md](../CHANGELOG.md); the user guide is [guide.md](guide.md). When behaviour changes, update the section here and add a changelog entry.

Built and tested on macOS, Anki 26.9.2; also installed on Windows.

## Goal

Run an AI study loop inside the Anki desktop reviewer: the AI turns each card into rewritten questions, the user types free-text answers, the AI grades them and recommends an ease, and the user still presses Anki's own Again / Hard / Good / Easy. The add-on never calls the scheduler.

## Layout

| Module | Role | Imports Anki? |
|---|---|---|
| `__init__.py` | Loads `main.py` only inside Anki | guarded |
| `main.py` | Hooks, AI Study toggle, reviewer glue, side-panel chats | yes |
| `ui.py`, `panel_page.py` | Reviewer HTML/JS; the side chat panel's page | no |
| `side_panel.py` | The chat panel: docked in the main window, attached to the Add Cards window | yes |
| `chat_page.py` | `ChatPage` base for both pages (state enter/leave, Back, chat box, bridge routing); `load_config` / `save_config`, `deck_ids` | yes |
| `synced.py` | Which settings sync with the collection and where they live in it; load, save, one-time migration (takes a `Collection`) | no |
| `config_page.py`, `generate_page.py` | ⚙ Settings and ✨ Generate/Update Cards pages | yes |
| `session.py` | Provider CLIs: find, isolate, run, parse; login; model lookup | no |
| `textutil.py` | Shared text helpers: style guide, HTML to text, JSON reply parsing, safe rich text | no |
| `grading.py` | Tutor prompts and reply parsing | no |
| `note_chat.py` | Prompts and replies for chats about a note (highlight-to-ask, Add Cards) | no |
| `missed.py` | The Missed section of a note | no |
| `config_ops.py` | Settings chat prompt, validated config changes, toggles | no |
| `generate_ops.py` | Generate prompt, reference reading, reply validation | no |
| `generate_col.py` | AI-GEN staging ops on a `Collection` passed in | no |
| `health.py` | Self-check, error classification, reviewer failure policy, update / rollback | no |
| `fixes.py` | Fix buttons on Settings replies; talks to the page only through `cfg`, `provider`, `apply`, `login`, `say`, `refresh` | yes |
| `state.py` | What the add-on learns about the CLIs: real model names, `last_good` versions. `user_files/state.json`, kept by Anki across updates; never in the config or its undo history | no |
| `style.md` | Formatting guide (bold, note-field HTML, LaTeX) appended to the tutor, note-edit and Generate system prompts | — |
| `config.json` | Shipped defaults (this computer's settings live in the gitignored `meta.json`; synced ones in the collection, see Synced settings) | — |

Everything that doesn't import `aqt` is unit-tested with plain pytest.

## Providers and sessions (`session.py`)

- `provider`: `claude` (default) or `codex`. Uses the user's logged-in CLI; no API keys. CLI paths `claude_path` / `codex_path` are auto-detected when empty, including when Anki is launched from the Dock (no shell `PATH`).
- **Windows**: every CLI call uses UTF-8 pipes and, on Windows, no console window (`session.PROC_KW`). The Claude system prompt is passed as a file (`--system-prompt-file`, written into the session's temp folder by `session.system_prompt_file`), never as an argument: npm installs `claude.cmd`, and `cmd.exe` cuts arguments at the first newline. The test suite runs on Windows, macOS and Linux in GitHub Actions (`.github/workflows/tests.yml`), using `.cmd` wrappers for the fake CLIs on Windows. Rollback needs the Mac/Linux install layout; elsewhere it offers no versions.
- **Stateless requests**: every prompt carries the card, questions, answers, deck prompts and the card's last Missed section. No conversation memory is relied on.
- **Claude**: one long-running `claude -p --input-format stream-json --output-format stream-json --verbose` per review session, kept only to skip startup. Starts on first request; stops when review ends, on profile close and on app exit.
- **Codex**: one `codex exec --json … -` per message, system prompt prepended on stdin; answer = last `agent_message` event.
- **Isolation** (both run in an empty temp directory with no user settings, hooks, plugins, MCP servers or tools):
  - Claude: `--safe-mode --setting-sources "" --strict-mcp-config --tools "" --disable-slash-commands --no-session-persistence`. `--bare` is not usable: it can't use subscription login.
  - Codex: `--ephemeral --ignore-user-config --ignore-rules --skip-git-repo-check -s read-only --disable shell_tool|apps|browser_use|computer_use|plugins -c web_search="disabled"`.
- API: `request(card_id, prompt, parse, timeout, callback)` — callbacks on the main thread; the "ask" and "grade" prompts come from `grading.py`. One request in flight, later ones queue. Replies are tagged with their card id; replies for a card no longer shown are dropped.
- **Models**: `models: {claude, codex}`; `""` = the CLI's default. Settings always shows the real model id, read from the CLI's own output (Claude's stream-json `init` event, Codex's stderr `model:` header), saved by `session.remember_model` into `state.py` the moment a probe or real call reports it (rendering never writes). The two keys older versions kept in the config (`resolved_models`, `last_good`) are dropped on the next settings change.
- **Login**: Claude `claude auth status|login|logout`; Codex `codex login status` / `codex login` / `codex logout`. On Windows, login runs in its own console window (`CREATE_NEW_CONSOLE`, no captured output): the CLI may print a sign-in link and wait for a pasted code, which a hidden process can neither show nor receive. Elsewhere it runs hidden and the CLI opens the browser.

## Reviewer flow (`main.py`, `ui.py`, `grading.py`)

Only active while **AI Study** is ON, and only for cards whose home deck has AI Study on (per-deck setting, default on; see Deck Settings in Settings). The ON/OFF link is on the home screen, on the deck overview and in **Tools → AI Study mode**. It stays as the user last left it across Anki restarts (`state.json` → `ui.ai_study`; off on first install). Off means the plain reviewer runs and no AI process starts; turning it off kills the session. The flow is display-only, through `gui_hooks.card_will_show`: nothing is written to the card except the Missed section.

**Question side**
- Rewrite question is on by default and set per deck (see Deck Settings in Settings). When on for the card's home deck, an ask request carries only the card's front (question) and deck rules, never the back, and returns `{"questions": [1–4], "hints": [...]}`, one question per distinct point the card bundles (at most 4 by default; deck rules override the defaults, up to 8 questions). `"show_original": true` opens **Show original** above the questions, e.g. when a deck rule says to present the card's question as written. A question that asks for several parts comes as `{"question": stem, "parts": [...]}` and its hint as a list, one per part. The add-on numbers questions `1.`, `2.` (only when there are several) and parts `3.1`, `3.2` (or `1.`, `2.` under a single question). Each hint (short, never the answer) shows as a **?** tooltip on the smallest unit: after each part, or after the question when it has no parts. Missing hints are allowed. A question with parts still has one answer box; the prompt says so, so "a box per section" deck rules come back as separate questions. `parse_questions` returns plain-text `questions` (parts as numbered lines, used by the grade and edit prompts and the verdict, which numbers its rows the same way) and `items` for the question side. Otherwise the card's own question is used.
- Rewrite question off, but a deck prompt applies (own or inherited): the ask request still runs (`config_ops.ask_mode` → "keep"). The card's question shows as written, with no Show original fold, and no box until the reply arrives. The AI is told not to repeat or rephrase it and to return only what the deck rules add on the question side, or `"questions": []`. `parse_added_questions` accepts an empty list, and `setQuestions([])` then gives one plain box. That way deck prompts shape the question side (sections, box count, show original) as well as grading. The Settings panel notes this next to the switch. With no deck prompt and the switch off, there is no ask request.
- Cloze cards always use their own blanked question.
- Layout: a collapsed **Show original** (Anki's normal question) at the top, then a question + answer box pair for each question. With rewritten questions, no box is shown until `ask` returns (only "Thinking of a rewritten question…"). If `ask` fails, one box appears under the opened original. Without rewritten questions (or for cloze), the original is shown with its box ready at once.
- **Enter** moves to the next box and submits from the last; **Shift+Enter** is a newline. Anki's shortcuts don't fire while typing. Anki's own Space and **Show Answer** (`Reviewer._showAnswer`, wrapped by `main.around_show_answer`) grade too, with blank boxes sent as "(blank)" via `aiStudy.submitNow()`. Enter with all boxes empty is the explicit skip: it shows the answer without grading. With no boxes yet (`ask` pending), or after a failed grading, Space just shows the answer. Cards with AI Study off keep Anki's behaviour.

**Answer side**
- A grade request returns `{"verdict": "wrong"|"partial"|"correct", "ease": 1-4, "feedback", "missed": [str], "per_question": [...]}`.
- The full card is sent again, so grading works even if `ask` failed or was skipped.
- The rubric is fixed: wrong 1, partial 2, correct 3, correct + complete and crisp 4. Missed bullets are short (the prompt caps hints, notes, whys and Missed items at about 15 words) and contain only reference facts the user left out.
- The verdict (badge, the user's answer, feedback, per-question marks, Missed bullets) is inserted just below the front of the card, right after `<hr id=answer>` (Anki scrolls it to the top), above the normal answer. Each `per_question` item carries `parts`: the user's answer clipped into claims in their own words, each with a verdict and, unless correct, a `why`. Colour follows verdict (green / orange / red); without parts the whole answer is coloured by its grade. Verdicts agree upward: a question is no better than its weakest claim, the card no better than its weakest question. The recommended ease button is outlined; the user presses a button themselves.

**Highlight to ask** (both sides, whenever AI Study is on for the card)
- Selecting card text shows a small **AI** bubble at the highlight (`ui.ask_html`). Selections that start inside an answer box are editing, not asking. Clicking the bubble opens the side panel and shows the highlight as a quote above the chat box; the full highlight is what the AI receives, and the quote stays above the message it was sent with.
- The panel (`side_panel.ReviewPanel`) is docked on the right of the main window, which widens by the panel's width so the card keeps its size and position (it slides left first if it would leave the screen; a maximized window can't grow, so the card area gives way). × closes it and shrinks the window back. **Clear** empties the conversation (the AI backend keeps its memory until the session ends).
- The conversation lives in the panel page, so it survives card changes and ends with the review session, turning AI Study off or closing the profile. One message is answered at a time; replies for cleared messages are dropped. Your messages start with `> `, replies with `● ` (same in the Settings and Generate chats).
- Question side (`note_chat.question_side_prompt`): only the card's question and the questions shown, never the answer; the AI never edits.
- Answer side (`note_chat.edit_prompt`): the note's raw fields, the grade when graded, deck rules and the highlight. Questions are answered without changes; change requests edit the note; one message can do both. Only existing fields that differ are written, as one undo step (`update_note` with no initiator, so the reviewer redraws).
- It runs on a separate backend (`note_chat.EDIT_SYSTEM_PROMPT`) so the tutor conversation stays clean. The reply is `{"reply", "fields"}`. Its failures don't count toward the study failure policy.

**AI panel in the Add Cards window** (only while AI Study is on)
- An **AI Study** button on the Add Cards window (`gui_hooks.add_cards_did_init`) toggles a panel (`side_panel.AddPanel`) attached to the window's right edge. It follows the window and uses the same page and backend as highlight-to-ask, with no highlight quote.
- Prompt: the fields typed so far (saved first), the selected deck's rules and the question (`note_chat.new_note_prompt`). Answers only: `fields` is ignored and nothing is written.
- The Browser editor has no panel yet.

**Missed section** (`missed_append`, default on; `missed.py`)
- The note keeps one `<hr><b>Missed (date)</b> <i>N reviews</i><ul><li><b>[K]</b> point</li>…</ul>`: the latest review's date, the number of graded reviews, and per point how many of them missed it. Points missed often are marked in red (`missed.RED_FROM`).
- Each review adds one to the points missed again and adds new ones; the others keep their count. Points are matched by normalized words, not exact text, so rewording doesn't start a second counter. Most-missed first; capped (`missed.MAX_MISSED`). Older formats are still read.
- It goes into the first existing field of `Back` → `Back Extra` → the note's last field. The tutor prompt treats it as past gaps, not required content, and asks for repeats in the listed point's own words.
- A write failure shows a note in the verdict; the review is unaffected.

**Formatting** (`style.md`, `textutil.rich`)
- `style.md` is the only place formatting rules live. It is appended to every system prompt (tutor, note chat, Generate), so all providers follow one guide.
- Short texts are shown through `textutil.rich` (HTML-escaped, then `**x**` → `<b>`); the same goes for Missed bullets saved into the note.
- Math is LaTeX in `\( \)` / `\[ \]`. Anki typesets the card once; later-arriving text is typeset on arrival.
- `textutil.parse_json_reply` repairs the usual LaTeX slips in JSON (single backslashes). A single-backslash `\neq` can't be told from a newline and stays broken.

**Prompt context**: rendered question and answer as plain text (no images); the ask request gets the question only, grading gets both. Custom Generic Rules go in the system prompt; each card sends its own home deck's prompt chain (`card.odid or card.did`, root → leaf, inner wins). Priority, highest first: deck rules, Generic Rules, then the built-in tutor defaults and `style.md`; only the JSON reply format is fixed. The note-edit prompt gives deck rules the same top priority. Deck rules reach both the question side and grading, whatever the Rewrite question switch says.

## ⚙ Settings (`config_page.py`, `config_ops.py`)

A main-window state (`aiStudyConfig`, **← Back** → deck list).

- **Chat**: each message goes to a separate CLI call; the AI replies `{"reply", "changes"}`. `config_ops.apply_changes` validates each change: `set` known keys with type/range checks, `add_custom` / `remove_custom`, `set_deck_prompt` / `clear_deck_prompt`, `set_deck_ai` / `set_deck_sharp` (`on`: true / false / null = follow parent), `undo` (snapshot restore), `login` / `logout`. Saving uses `chat_page.save_config` (see Synced settings).
- The log shows the latest 3 replies; rejected changes appear in red inside the reply. The Settings AI gets the real model in use, never lists or guesses model names, and points to the Model dropdown.
- **Configurations**:
  - Provider and Model rows: dropdowns. The model list is loaded live from the CLI and never stored.
  - Login state, timeouts, and the CLI version with **Update**.
  - **Missed append**: On/Off toggle. `config_ops.TOGGLES` is the single source for each toggle's label and help text. Clicks go through `apply_changes`. Each toggle has a CSS **?** help bubble.
  - Plain controls always work, even when the provider's AI is broken.
- **Custom Generic Rules**: numbered rules, applied to every card.
- **Deck Settings**:
  - Clicking a deck starts the chat box with `Deck prompt for "<deck>": ` and focuses it (`config_page.deck_prefix`). Clicking another deck swaps the prefix and keeps anything typed after it. Clicking the selected deck again deselects it: its folder closes and the prefix is removed (text typed after it stays). The tree lists decks as Anki's deck list does, so an empty Default deck is hidden (`all_names_and_ids(skip_empty_default=True)`). A message the user wrote themselves is never replaced. The chat box is pinned to the top while the page scrolls.
  - The real deck tree, with ● marking decks that have a prompt.
  - Selecting a deck shows its panel directly under it in the tree (a selected parent expands): its own prompt, the ones it inherits, and the deck toggles with which deck decides each.
  - Deck toggles (`config_ops.DECK_TOGGLES`): **AI Study** (`deck_ai`; off = plain reviewer for that deck's cards) and **Rewrite question** (`deck_sharp`), each `{deck_id: bool}`. The innermost deck on the path with a setting wins; none = on. Each panel On/Off button flips the selected deck's effective value. Setting a deck (button or chat) drops its subdecks' own settings, so they follow it at once. A subdeck set afterwards stays as an exception until one of its ancestors is set again. Updates keep the page's scroll position. A deck prompt can't switch them: the decision is made before any AI call, so the Settings AI uses `set_deck_sharp`. The old global `sharp_questions` key is dropped on the next settings change.
  - In the config these are `deck_prompts: {deck_id: prompt}`, `deck_ai`, `deck_sharp`; they are stored on the decks themselves (see Synced settings), so they survive deck renames and go away with a deleted deck.
  - Deck names resolve exact → case-insensitive → unique leaf name; anything else is rejected.
- Changes apply from the next review session. Unsent drafts and in-flight replies survive leaving the page (in memory until Anki restarts).

## Synced settings (`synced.py`, `chat_page.load_config` / `save_config`)

Anki sync carries the collection, never add-on files, so settings that should follow the user live in the collection. The rest of the add-on sees one config dict with the same keys as before.

| Settings | Stored in | How Anki sync merges it |
|---|---|---|
| Deck prompt, AI Study, Rewrite question | each deck object, key `anki_ai`: `{"prompt", "ai", "sharp"}` (only the ones set) | per deck: the newer deck wins, so edits to different decks on different devices both survive |
| `custom`, `missed_append`, `ask_timeout_s`, `grade_timeout_s` | collection config `anki_ai` | the whole config table comes from the side whose collection changed last; an unsynced edit can lose to the other device |
| `provider`, `models`, `claude_path`, `codex_path` | `meta.json` | not synced: they depend on the computer |

- `save_config` writes `meta.json` (device keys) and only the parts of the collection that changed since the config it started from: an unchanged deck keeps its modification time so it doesn't win a later sync by accident, and only the general settings that changed are written into `anki_ai` (so a fresh computer's defaults never land there).
- Migration, once per profile per computer (`state.json` → `synced`): settings the user saved in `meta.json` (never `config.json` defaults) are merged in. What another device already synced wins where both set the same thing (it was set after this computer's old settings); everything else is added: missing general settings, custom rules not already there (appended), and deck fields a deck doesn't carry yet. With auto sync on (`mw.can_auto_sync()`), migration waits for the first `sync_did_finish`, so the other device's settings are there to merge with; writing before that sync would make this collection the newer one and its config would replace theirs. The old keys stay in `meta.json` unread, for other profiles.
- A deck setting change is a normal Anki undo step ("Update Deck"); earlier undo history is kept. General settings are written without an undo step.
- After a sync (`sync_did_finish`), a pending migration runs and an open Settings page redraws. Everything else reads the collection on use.

## ✨ Generate/Update Cards (`generate_page.py`, `generate_ops.py`, `generate_col.py`)

A main-window state (`aiStudyGenerate`). It works whether AI Study is on or off, with the same chat pattern as Settings.

- **References**:
  - Chosen with **Choose folder…** / **Choose file…** (native pickers opening on the Desktop) or cleared with **×**. The path box is read-only.
  - Must resolve to something strictly inside the Desktop: `~/Desktop`, or on Windows the folder the shell reports (OneDrive often moves it to `~/OneDrive/Desktop`; `generate_ops.desktop`).
  - Text files only. Binary and non-UTF-8 files are listed as skipped. Hidden files, `.git`, `node_modules`, `__pycache__` and venvs are ignored.
  - Limits: ≤ 300 files and ≤ 150k characters per message; anything cut off is reported.
  - Re-read on every message.
- **Fresh CLI process per message**: references and cards would overflow one long conversation, so the last 3 exchanges are resent as context.
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
| CLI missing / not logged in / crash / other error | "AI error: <message> — open ⚙ Settings to fix it." | crashed process respawns on next call; 2nd failure → "AI unavailable: <message>", AI off until the reviewer is reopened |
| Usage limit | "Usage limit: <message>" | AI off until the reviewer is reopened |
| Timeout (`ask_timeout_s` 30, `grade_timeout_s` 60) | "AI timed out." | late reply dropped |
| Non-JSON reply | — | one retry with "JSON only", then error |
| Missed write fails | red note in verdict | review unaffected |
| Anki closes mid-request | — | process killed, late callbacks ignored |

- **Self-check** (`health.self_check`):
  - Runs when Settings opens and after update or rollback.
  - `session.startup_check` starts the real study command and stops before any answer, so a pass proves the CLI accepts every add-on flag. Claude: until its `init` event names the model. Codex: the command without `--json` until its header names the model, then the exact `--json` command until its first event.
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
