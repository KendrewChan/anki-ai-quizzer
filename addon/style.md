# Formatting style

Plain, concise text. Cut filler, never key facts. Deck rules override this guide.

## Short texts
Questions, hints, feedback and missed points: plain text, no HTML or lists. Use **bold** for at most one key term.

## Chat replies
One point per line: "- " bullets, or "1. " for ordered steps. For several topics, use **topic** headings with a blank line between groups. No HTML; bold sparingly.

## Note fields
Anki HTML, not Markdown. Preserve existing formatting unless asked to change it.
- <b> for the key term, <i> for a definition or title, <code> for code.
- For subtopics, use <h3> headings and one point per bullet. Use <ol> for steps, <ul> otherwise; short answers can stay plain.
- Use a compact <table> for comparisons, not decoration.
- Colour only short recall cues, sparingly across sections: blue #3b82f6 = core idea, amber #d97706 = reason or pitfall, purple #a855f7 = names, numbers or formulas. Never red/green or whole sentences.

## Math
Use LaTeX: \( ... \) inline, \[ ... \] displayed; never $ ... $. In JSON, double every backslash ("\\(x^2\\)").

## Note template
Use only the pieces needed; omit empty sections. Replace placeholders; do not copy them literally.
```html
<b>Key term</b>: concise answer.
<h3>Subtopic</h3>
<ul><li>One fact, with a <span style="color:#3b82f6">core cue</span>.</li></ul>
<table><tr><th>Attribute</th><th>A</th><th>B</th></tr><tr><td>...</td><td>...</td><td>...</td></tr></table>
```
