# AI Quizzer for Anki — full guide

Study in the Anki reviewer with an AI tutor (Claude Code or Codex): it turns each card into rewritten questions, you type free-text answers, it grades them and recommends a button — you still press Anki's own Again / Hard / Good / Easy, so scheduling is untouched.

## Requirements

- Anki desktop (built and tested on 26.9.2, macOS).
- One AI CLI, installed and logged in with **your own** subscription — the add-on runs it locally and never sees your credentials:
  - [Claude Code](https://claude.com/claude-code) (`claude auth login`) — default, fastest (keeps one process open per study session), or
  - [Codex CLI](https://github.com/openai/codex) (`codex login`, ChatGPT plan) — ~6 s per card.

## Install

1. Get `anki_ai.ankiaddon` (build it with `python3 scripts/package.py` → `dist/`).
2. Anki → **Tools → Add-ons → Install from file…** → pick the file → restart Anki.

## Use

- Under the deck list (and under **Study Now**): **AI Study: OFF · 🤖 AI Window**. Click AI Study to turn it on or off — Anki remembers your choice next time it starts. Also in **Tools → AI Study mode** and **Tools → AI Window**.
- While reviewing: type answers (Enter = new line; **Ctrl/Cmd+Enter** or the **Show Answer** button grades if anything is typed, otherwise just shows the answer; **Space** only shows the answer, never grades). **Show original** reveals the card's real front. Rewrite question is on by default and the answer boxes appear once they arrive; hover a **?** for a hint. A question with several parts lists them as 3.1, 3.2, … with a hint on each part. Formulas show as rendered math, and the AI bolds at most one key term. To answer a deck's cards as written (faster: one AI call per card), tell the chat "don't rewrite questions for <deck>"; subdecks follow.
- The verdict shows right below the front of the card (already in view when the answer appears), above the card's answer; the recommended button is outlined. A question you leave empty is marked skipped, not wrong. Your answer is split into points coloured by how right they are, with a short reason on the wrong ones. The card's Back keeps one **Missed** section that adds up over reviews: each point shows how many reviews missed it, most-missed first, in red when often (**Missed append** in settings).
- **Highlight to ask:** highlight card text and click the blue **AI** bubble. A chat panel opens on the right (the window widens, so the card stays put) with your highlight quoted above the chat box. On the front it helps you understand the question without giving the answer away; on the back it can also change the note (Edit → Undo reverts). It's the same chat as in the AI Window, so you can also ask it anything else, have it look things up on the web, make cards ("make 3 more cards like this one" — they wait in Generate/Update for your approval) or change settings ("grade this deck more strictly"). The conversation stays as you move between cards; **Explain** above the chat box asks for an explanation of the highlight in one click; **Clear** empties the chat and the AI forgets it, × closes it.
- **Ask while adding cards:** with AI Study on, Anki's Add Cards window has an **AI Study** button that opens the same kind of chat beside it. It sees the fields so far, answers questions, and can fill in or change the fields in the editor when you ask (nothing is saved until you click Add). It can also search your other notes (for duplicates, or to match your existing card style); the reply lists what it searched for.

## AI Window (🤖 AI Window)

One window for the add-on's AI features: **⚙ Settings**, **✨ Generate/Update** and **📋 Today's Missed** as tabs on the left, and a chat on the right. It's a separate window, so you can keep it open while you review.

The chat works like a general AI assistant: ask anything, and it can search and read the web and read files on your computer (it cannot change or run anything itself). It can also act on your Anki from any tab: change settings, make or update cards, or go through what you missed today. It sees your settings, every deck's cards, the staged cards and today's misses from whichever tab you're on. It remembers the conversation until you press **Clear** or quit Anki (closing the window keeps it). Nothing is saved between Anki runs: deck prompts and rules are where lasting instructions belong. The chat is always open on the right. Highlight text in any tab and click the blue **AI** bubble to ask about it.

## Settings (⚙ Settings)

Tell the chat what you want in plain words — "use opus", "give me 90 seconds to answer", "grade more strictly", "for this deck, ask for code", "undo that".

- **Configurations** — provider (Claude Code / Codex; "use codex"), model ("default" = the provider's), timeouts, **Missed append** On/Off button (hover the **?** for what they do), CLI path (auto-detected), login with **Log in** / **Log out**.
- **Custom Generic Rules** — apply to every card.
- **Deck Settings** — click a deck and the chat box on the right starts with `Deck prompt for "<deck>": `, so you only type the prompt and press Enter. The chat adds it to the deck's prompt (it replaces the old one only if you say so) and quotes the result, so you can check nothing was lost. Click it again to close it and clear the prefix. One prompt per deck; subdecks inherit their parents'. Each deck's panel opens right under it and has **AI Study** and **Rewrite question** On/Off buttons (or say "no rewritten questions for this deck"); AI Study off = that deck reviews normally, without AI. Switching a deck makes all its subdecks follow; switch a subdeck afterwards to make an exception, which lasts until a parent is switched again. Click a deck to see what applies to it. A deck prompt can reshape the questions, e.g. "show the question as written, then one box each for Requirements, APIs, Data Store" (up to 8). A deck prompt that mentions misses (e.g. "in each section's hint, point at what I missed before") lets the AI see the card's Missed points when it writes the questions. This works even with **Rewrite question** off. Off then means the AI keeps the card's question unless the deck prompt says otherwise.

**On several computers:** deck prompts, the deck On/Off buttons, Custom Generic Rules, timeouts and Missed append sync with your collection when you press Sync. Provider, model and CLI path stay per computer. Install the add-on on each computer; settings arrive with the first sync. A computer that had settings from an older version merges them in after its first sync; where another computer already set the same thing, that newer setting is kept. If you change the same setting on two computers without syncing in between, the most recent change wins (for decks: per deck; for the rest: the computer whose collection changed last). Sync before switching computers.

**Windows login:** **Log in** opens a Claude Code window. Sign in in your browser (if it doesn't open, use the link in that window), and paste the code into that window if it asks for one.

## Browse window

With AI Study on, select text in a note in Anki's Browse window and click the blue **AI** bubble (or **AI Study → Chat about this note** in the menu bar). A chat opens at the window's side about that note: ask questions or ask for changes to its fields. Edits are one undo step (Edit → Undo).

## Big rewrites run in batches

When a request changes every card of a deck (e.g. "colour-code my SystemDesign cards"), the AI works 10 cards at a time. Staged cards appear after each batch, the status shows `Batch 2 of 5`, and Submit waits until it's done. Press **Stop after this batch** to end early; the cards already staged stay.

## Today's Missed (📋 Today's Missed)

Lists the notes whose Missed section was last written today, grouped by deck, with each missed point and how often it was missed. Read-only; a note reviewed again tomorrow moves to tomorrow's list. Ask the chat about them ("quiz me on what I missed", "make cards for my top misses").

## Generate/Update Cards (✨ Generate/Update Cards)

A tab of the AI Window. Optionally pick a **reference** — a file or folder on your **Desktop** (Choose folder… / Choose file…; text files only, e.g. .txt, .md, code). Then tell the chat what you want: "10 cards from these notes into Biology::Ch3", "improve my Chem cards using this file", "make card 3 shorter", "cards on the latest Python release from python.org". Cards made from any chat (the reviewer's too) land here; the reply has a **Review in Generate/Update** button.

- New and updated cards wait in a temporary deck, **AI-GEN**, whose subdecks mirror where they'll go (`AI-GEN::Biology::Ch3`, or `AI-GEN::Physics` for a brand-new deck). Nothing in your real decks changes yet — you can study or edit them there.
- On an UPDATE card, **Show Original** shows the card as it is now, fully expanded (click **Show Update** to go back).
- **Approve** cards (each card, a whole deck, or all) — they stay in AI-GEN with a ✓ so you can keep generating; **Unapprove** changes your mind, **Discard** throws a card away.
- **Submit** moves only the approved cards: updates are written into the original cards (review history kept), new cards go into their real decks, created if needed. Unapproved cards stay in AI-GEN. AI-GEN disappears once it's empty. Everything can be undone with Edit → Undo.

## When something breaks

Open **🤖 AI Window → ⚙ Settings**: it checks your AI CLI on open. If something's wrong you get a plain explanation with buttons — **Update**, **Roll back** to the last version that worked, **Log in**, **Allow more time**, switch provider, or **Copy error report** to send to the author.

## Notes

- Studying uses your own plan's usage (Claude or ChatGPT). Grading keeps one `claude` process open per review session; Codex starts one per message. Each chat keeps its own (read-only file tools, web search and web fetch are its only tools).
- Built and used on macOS. Windows and Linux are covered by automated tests but not yet tried in Anki itself. If the CLI isn't found, tell the chat its path ("claude path is /path/to/claude", or the same for codex).

## Development

- `addon/` is the add-on; symlink it into `addons21/anki_ai` to develop live.
- Tests: `pytest tests` (no Anki needed; `session.py` runs against `tests/fake_claude.py`). `tests/test_generate_col.py` needs Anki's Python (see its docstring) and is skipped otherwise.
- Design: `spec.md`.
