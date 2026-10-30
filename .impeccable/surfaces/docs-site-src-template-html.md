---
version: 1
slug: "docs-site-src-template-html"
primary_target: "docs/site/src/template.html"
related_targets: ["docs/site/index.html"]
---

# Surface: AgentScript docs site (docs/site/src/template.html -> docs/site/index.html)

Mode: Read. Reader: an examiner on a laptop who wants to understand how the compiler works and check the claims against real output. Source: every doc in docs/ plus the 18 examples, bundled by docs/site/build.py. Wayfinding: sidebar tree by division, search, on-page contents, prev/next.
Must keep: every page, search, TOC scrollspy, Mermaid, copy buttons, theme toggle, examples gallery, GitHub links.
Shares the editor's world (see web/index.html brief): the world owns the frame (masthead, rail, division signs, code/table setting); the reading column stays calm.

## Direction contract

THESIS: The documentation is the terminal's wayfinding: you always know which division you are in and which gate comes next. Refuses the dark-gradient-hero docs template.

OWN-WORLD: Same programme as the editor: signage yellow masthead, black numeral tiles, terminal-grey ground, white reading sheet. Division hues as an index: Start here green, Specification blue, How it works yellow, Presentation and Reference ink. Atkinson Hyperlegible Next (reading and headings), Atkinson Hyperlegible Mono (code).

STORY: The reader lands, sees the two channels (a rejected program with its real E401, the fixed one compiling), follows the ten gates into how-it-works, and reads each phase with prev/next gates.

FIRST VIEWPORT: Yellow masthead with brand sign, search, Editor, Examples, GitHub, theme. Left rail of division signs. Main: title and one-paragraph answer, then the red/green channel pair side by side with real compiler output, then the ten-gate row linking to phases.

FORM: Arrivals-hall wayfinding, candidate 3 of 7; seed:05378282589929f9. Raise from acetate tab board: one hue per division at full strength, only as an index.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
