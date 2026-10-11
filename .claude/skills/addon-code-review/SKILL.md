---
name: addon-code-review
description: Use when asked to review, audit or clean up the "AI Quizzer" Anki add-on in this repo (anki-ai-quizzer, package anki_ai) — code quality, personal information / privacy before publishing, user-specific code, good coding principles, or "review the add-on with subagents".
---

# Add-on Code Review

## Overview

A full review of the add-on uses parallel subagents that **only report**. You verify each finding yourself, fix the ones that hold up, and ship the fixes through the `anki-update-addon` skill (tests, docs, commit, deploy). The repo is **public**, so a privacy audit is always part of the review.

## Workflow

1. **Orient**: `git status` (don't clobber another session's uncommitted work), `git ls-files | xargs wc -l | sort -n` to split the code into even groups by size.
2. **Launch reviewers in parallel** (one message, several Agent calls; at most about 5). Each prompt says **REPORT ONLY — do not edit, commit or push**, names the files it owns, says to skim `docs/spec.md` and `.claude/skills/anki-update-addon/SKILL.md` first, and asks for findings as `file:line`, severity (bug / risk / cleanup), what's wrong, a concrete failure scenario for bugs and a suggested fix, most severe first, under ~600 words, verified by reading the code, no style nitpicks.
   - **Privacy auditor** (always): every tracked file, the images in `docs/images/` (view each), untracked scripts, and git history (`git log --all -p`, commit messages, author fields). It looks for real names, emails, usernames, home or Windows user paths (`/home/`, `/Users/`, `C:\Users`, `/mnt/c/Users`), secrets (`sk-`, `ghp_`, api keys), real deck names and **card content in disguise**: examples in prompts, `style.md`, tests or the changelog copied from the user's own flashcards. Generic textbook examples (photosynthesis, `Biology::Ch3`) are fine. It reports current files apart from history-only hits.
   - **Code reviewers**, split by area, for example:
     - Provider and plumbing: `session.py`, `health.py`, `fixes.py`, `state.py`, `errorlog.py`, `synced.py`, `__init__.py`, `config.json`, `manifest.json`, `scripts/`, with their tests and fakes.
     - Reviewer and grading: `main.py`, `ui.py`, `grading.py`, `missed*.py`, `note_chat.py`, `textutil.py`, `style.md`, `panel_page.py`, `side_panel.py`.
     - Chat, settings and Generate: `assistant*.py`, `config_*.py`, `generate_*.py`, `ai_window.py`, `tab_page.py`, `missed_page.py`.
   - Each code reviewer checks three things:
     1. **User-specific code**: prompts, examples or defaults tuned to one person's decks or subject; hard-coded deck names, paths or model names (models come from the CLI); OS assumptions (it must run on Windows, macOS and Linux).
     2. **Correctness**: unescaped AI or user text in HTML or JS, AI-returned actions applied without validation, threads and subprocesses (`session.PROC_KW` on every subprocess), collection ops not batched into one undo step, stale replies after the card changes, swallowed errors.
     3. **Good practice**: dead code, duplication, functions doing too much, misleading names or docstrings, drift from `docs/spec.md`, prompts that contradict each other, important logic without tests.
3. **Verify every finding** before acting: open the cited lines and confirm the failure scenario. Drop false positives and say why. Reviewers are often wrong about intent the spec documents.
4. **Fix** what holds up, following `anki-update-addon`: keep logic in Anki-free modules with tests, add a test for each bug fixed, put formatting rules only in `style.md`. Leave large redesigns as suggestions for the user rather than doing them unasked.
5. **Verify**: `uvx --native-tls pytest -q -p no:cacheprovider tests` and `python3 -m py_compile addon/*.py`.
6. **Privacy gate before committing**: `git diff` checked for anything personal; `addon/meta.json`, `user_files/` and `dist/` stay untracked.
7. **Record, commit, deploy** as in `anki-update-addon` (spec, changelog for anything user-visible, a descriptive commit, push, deploy and restart notice).
8. **Report**: what was fixed (with commits), what was dismissed and why, and what's left as a suggestion. Personal info that is only in git history needs a history rewrite and a force-push, so ask the user before doing that; never do it unasked.

## Common Mistakes

| Mistake | Fix |
|---|---|
| Letting reviewers edit files in parallel | Reviewers only report; one agent (you) applies fixes, so there are no conflicting edits |
| Fixing a finding without reading the code | Verify each one; subagents misread intent and line numbers |
| Writing examples from the user's own decks into prompts or docs | Use generic textbook examples; the repo is public |
| Rewriting git history to remove personal info without asking | Report it and ask: it needs a force-push |
| Claiming fixes work in Anki after tests pass | Tests use fake CLIs; say it's unverified until the user restarts Anki |
