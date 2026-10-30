---
version: 1
slug: "web-index-html"
primary_target: "web/index.html"
related_targets: []
---

# Surface: AgentScript editor (web/index.html)

Mode: Operate. Visitor: an examiner on their own laptop, exploring unaided after submission.
Job: pick an example, compile, read why it is accepted or rejected, inspect each phase, run a task.
Must keep: every feature (examples picker, 10-stage strip, 12 tabs, Compile/Run, Approve/Deny, Live
tools, A-/A+, Ctrl+Enter, Ctrl+Shift+Enter, squiggles, taint lines, path steps, CFG graph/text).
Avoid: generic SaaS template; a verdict that is hard to follow.
Shared world with the docs site (docs/site); see that surface's brief.

## Direction contract

THESIS: The compiler is a border crossing. Every program walks the ten gates and leaves by the green channel ("nothing to declare") or the red channel, with the exact declaration (code, line:col, path). Refuses the grey IDE-with-pill-tabs default.

OWN-WORLD: Airport wayfinding programme (Schiphol/Mijksenaar). Signage yellow #FFC917 masthead with black ink, cool terminal-grey ground, white panels, black numeral tiles. Channel green #00804A, channel red #CC1F2D, mandatory blue #1D5FBF for approval/confirm. Atkinson Hyperlegible Next for all UI, Atkinson Hyperlegible Mono for code. Drawn stroke pictograms, no glyph icons. Dark: lit signs on black.

STORY: The examiner sees at once which gate a program stopped at and why, jumps to the line, then runs it and sees the call log and budget.

FIRST VIEWPORT: Yellow masthead (brand sign, example picker, docs link, zoom, theme). Below it a full-width row of ten equal gate cells, each a numeral tile + name, coloured by result. Under that the channel sign: one full-width green/red/yellow band with pictogram and the verdict. Workspace: source editor left with Compile; output tabs right; run controls docked under the editor.

FORM: Arrivals-hall wayfinding and customs channels, candidate 3 of 7; seed:05378282589929f9. Raise from split-flap (declined): fixed cells; gates never move or reflow, only their state changes, tabular numerals. Raise from acetate tab board (competitive, Read): one hue per division, used as an index.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
