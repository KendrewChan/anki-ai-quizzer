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
- <ul><li> only for 3+ parallel items; keep reasoning ("because", "so") in sentences.
- <table> only to compare 2+ things on 2+ attributes; short cells.
- <code> for code, commands and identifiers.
- Colour, sparingly, with `<span style="color:#hex">` on a phrase (never a whole sentence, never a background); each colour has one meaning:
  - `#3b82f6` blue: a term or concept being defined.
  - `#d97706` amber: a warning: a pitfall, exception or trade-off.
  - `#a855f7` purple: a concrete example, number or value.
  - Never red or green (the add-on uses them for wrong / correct feedback). At most 3 coloured spans per note; if nothing fits a meaning, use none. The text must read correctly without the colour, and the key term stays <b>.
  - Keep a note's existing colours as they are unless asked; follow this scheme only for text you add or rewrite.

## Math (both kinds of text)
- LaTeX inside \( ... \) for inline math, \[ ... \] for a displayed formula. Never $ ... $.
- Use it for real formulas and symbols (\(O(n \log n)\), \(\frac{a}{b}\), \(x^2\)); plain words stay plain.
- Your reply is JSON, so every backslash is doubled in the JSON string: "\\(x^2\\)", "\\frac{a}{b}".
