# Formatting style

Plain, clear text first. Every format has one meaning; use it only when that meaning applies.

## Short texts (questions, hints, notes, feedback, missed facts)
- Plain text. **bold** (double asterisks) marks the one key term a skimmer must not miss — at most one per text, often none.
- No other Markdown, no HTML, no colours. No lists (a question's sub-parts go in its "parts" array).

## Chat replies ("reply")
Short text with one exception, because it is a conversation answer: when you make 2+ separate points, put each on its own line ("\n" in the JSON string) starting with "- ", or "1. ", "2. " when the order matters or the user asks for numbered points. A lead-in sentence may come first. A single point stays a sentence or two, with no list. One **bold** key term per point at most; no other Markdown.

## Note fields (cards you write or edit)
Anki HTML only, no Markdown:
- <b> for the one key term of the answer; <i> for a term being defined or a title. Never <u> (reads as a link).
- A topic with 2+ subtopics: one short intro line, then each subtopic under its own <h3> title with its points as bullets, one point per bullet, then a comparison <table> of the subtopics (one column each, a row per attribute they differ on: where, input, output…).
- Bullets: <ol><li> when the points are a sequence (steps, stages, a process in order), with a one-line lead-in before it and any point that isn't a step on a line after it; otherwise <ul><li>. Outside subtopics, a list only for 3+ items.
- Cut words, never facts: every key fact (term, number, cause, exception) stays; drop filler ("basically", "it is important to note", "on the other hand", "that is why", "in order to"). Fragments are fine, arrows (→) and "X: Y" for short links. A reason stays in its point's bullet ("stops in the dark: no ATP supply").
- Elsewhere, <table> only to compare 2+ things on 2+ attributes; short cells.
- <code> for code, commands and identifiers.
- Colour marks what the reader must RECALL, with `<span style="color:#hex">` on a phrase (never a whole sentence, never a background). First decide the deck's study goal from its deck rules, its name and the notes around it (e.g. "system-design interviews", "HSK vocabulary for an exam"), then mark what someone with that goal must be able to say from memory, not what merely looks important. Each colour has one meaning:
  - `#3b82f6` blue: the core: the main concept, decision or answer the section is about.
  - `#d97706` amber: the why: the trade-off, the reason an alternative is rejected, the pitfall or exception.
  - `#a855f7` purple: anchors: numbers, thresholds, names and formulas that can't be derived.
  - Cover every section: each paragraph, bullet group or numbered step gets its core point (1-3 spans), so a long note ends up with about one coloured phrase per 40-60 words; a short note may have 2-3. Colour at most about a fifth of the text.
  - A span is a cue of 1-6 words: the key noun phrase or the decision itself, not a whole clause or sentence.
  - Never red or green (the add-on uses them for wrong / correct feedback). The text must read correctly without the colour, and the key term stays <b>.
  - Keep a note's existing colours as they are unless asked; follow this scheme only for text you add or rewrite. A deck rule can change the meanings, the colours or the amount.

## Math (both kinds of text)
- LaTeX inside \( ... \) for inline math, \[ ... \] for a displayed formula. Never $ ... $.
- Use it for real formulas and symbols (\(O(n \log n)\), \(\frac{a}{b}\), \(x^2\)); plain words stay plain.
- Your reply is JSON, so every backslash is doubled in the JSON string: "\\(x^2\\)", "\\frac{a}{b}".

## Example
A note on a study topic with two subtopics, for a deck whose goal is a biology exam, as stored in the field (in your JSON reply, escape the quotes and double the backslashes).

Good:
```
<b>Photosynthesis</b>: light energy → glucose, in the <i>chloroplast</i>. Two stages; the first feeds the second.
\[6\,CO_2 + 6\,H_2O \rightarrow C_6H_{12}O_6 + 6\,O_2\]
<h3>Light-dependent reactions</h3>
<ul><li>Where: thylakoid membranes</li>
<li>Light <span style="color:#3b82f6">splits water → ATP + NADPH</span></li>
<li><span style="color:#d97706">O₂ comes from water</span>, not CO₂ (exam trap)</li></ul>
<h3>Calvin cycle</h3>
<p>In the stroma, ATP + NADPH <span style="color:#3b82f6">fix CO₂ into sugar</span>:</p>
<ol><li>Fixation: RuBisCO adds CO₂ to a 5-carbon sugar (RuBP)</li>
<li>Reduction: ATP + NADPH → G3P</li>
<li>Regeneration: RuBP rebuilt; <span style="color:#a855f7">6 turns</span> per glucose</li></ol>
<p>No light needed directly, but <span style="color:#d97706">stops in the dark</span>: no ATP/NADPH supply.</p>
<table><tr><th></th><th>Light-dependent</th><th>Calvin cycle</th></tr>
<tr><td>Where</td><td>Thylakoid</td><td>Stroma</td></tr>
<tr><td>Inputs</td><td>Light, H₂O</td><td>CO₂, ATP, NADPH</td></tr>
<tr><td>Outputs</td><td>ATP, NADPH, O₂</td><td>G3P (sugar)</td></tr></table>
```

Bad:
```
<b>Photosynthesis</b> is basically the process by which plants are able to turn light energy into chemical energy that is stored in glucose. It is important to note that the light-dependent reactions, which take place in the thylakoid membranes, use light to split water, <span style="color:#3b82f6">and that is why plants release oxygen into the air</span>. The <b>Calvin cycle</b>, on the other hand, takes place in the stroma, where it uses the ATP and NADPH in order to fix carbon dioxide into sugar.
```
Why: the bad one runs both subtopics together in one paragraph with no titles, bullets, numbered steps or comparison table, pads with filler ("basically", "it is important to note", "on the other hand", "in order to"), uses two <b>, colours a whole clause, and spends more words on fewer facts. The good one cuts words, not facts: every term, number and pitfall is still there.
