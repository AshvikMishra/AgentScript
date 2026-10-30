---
name: AgentScript
description: A ten-gate compiler for safe AI agents, signed like an arrivals hall.
colors:
  signage-yellow: "#ffc917"
  sign-ink: "#16181d"
  tile-black: "#16181d"
  tile-numeral: "#ffc917"
  channel-green: "#00804a"
  channel-green-wash: "#e2f2e9"
  channel-green-text: "#006b3e"
  channel-red: "#cc1f2d"
  channel-red-wash: "#fbe5e6"
  channel-red-text: "#b01a27"
  mandatory-blue: "#1d5fbf"
  mandatory-blue-wash: "#e3ebf8"
  mandatory-blue-text: "#1a55ab"
  amber-wash: "#fff3c8"
  amber-text: "#7a5a00"
  amber-line: "#c08a00"
  on-channel: "#ffffff"
  terminal-grey: "#e9ebee"
  panel: "#ffffff"
  panel-2: "#f4f5f7"
  rule: "#d3d7dd"
  rule-strong: "#b7bcc5"
  ink: "#16181d"
  ink-2: "#464c57"
  ink-3: "#636a77"
  night-ground: "#0a0a0b"
  night-panel: "#141415"
  night-panel-2: "#1c1c1e"
  night-rule: "#2a2a2c"
  night-rule-strong: "#3d3d40"
  night-ink: "#eceef1"
  night-ink-2: "#b9bec7"
  night-ink-3: "#8f96a2"
  night-tile: "#000000"
  night-green: "#17794b"
  night-green-text: "#4fd08f"
  night-red: "#c92f3a"
  night-red-text: "#ff7a82"
  night-blue: "#2f6bd0"
  night-blue-text: "#8db4ff"
  night-amber-text: "#ffd65a"
typography:
  display:
    fontFamily: "Atkinson Hyperlegible Next, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "clamp(2.1rem, 3.4vw, 2.75rem)"
    fontWeight: 800
    lineHeight: 1.1
    letterSpacing: "-0.022em"
  headline:
    fontFamily: "Atkinson Hyperlegible Next, system-ui, sans-serif"
    fontSize: "1.6rem"
    fontWeight: 800
    lineHeight: 1.2
    letterSpacing: "-0.012em"
  title:
    fontFamily: "Atkinson Hyperlegible Next, system-ui, sans-serif"
    fontSize: "19px"
    fontWeight: 800
    lineHeight: 1.25
    letterSpacing: "-0.01em"
  body:
    fontFamily: "Atkinson Hyperlegible Next, system-ui, sans-serif"
    fontSize: "17px"
    fontWeight: 400
    lineHeight: 1.65
  body-ui:
    fontFamily: "Atkinson Hyperlegible Next, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.45
    fontFeature: "tnum"
  label:
    fontFamily: "Atkinson Hyperlegible Next, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 700
    lineHeight: 1.3
  code:
    fontFamily: "Atkinson Hyperlegible Mono, ui-monospace, SFMono-Regular, Consolas, monospace"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.6
  code-listing:
    fontFamily: "Atkinson Hyperlegible Mono, ui-monospace, monospace"
    fontSize: "13.5px"
    fontWeight: 400
    lineHeight: 1.6
  numeral:
    fontFamily: "Atkinson Hyperlegible Mono, ui-monospace, monospace"
    fontSize: "12.5px"
    fontWeight: 700
    lineHeight: 1
    fontFeature: "tnum"
rounded:
  micro: "2px"
  r-1: "3px"
  r-2: "6px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  gutter: "14px"
  lg: "20px"
components:
  button-compile:
    backgroundColor: "{colors.tile-black}"
    textColor: "{colors.tile-numeral}"
    typography: "{typography.label}"
    rounded: "{rounded.r-1}"
    padding: "0 16px"
    height: "42px"
  button-run:
    backgroundColor: "{colors.channel-green}"
    textColor: "{colors.on-channel}"
    rounded: "{rounded.r-1}"
    padding: "0 16px"
    height: "42px"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.r-1}"
    padding: "0 14px"
    height: "36px"
  button-docs-primary:
    backgroundColor: "{colors.tile-black}"
    textColor: "{colors.tile-numeral}"
    rounded: "{rounded.r-1}"
    padding: "0 14px"
    height: "40px"
  button-docs-secondary:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink}"
    rounded: "{rounded.r-1}"
    padding: "0 14px"
    height: "40px"
  numeral-tile:
    backgroundColor: "{colors.tile-black}"
    textColor: "{colors.tile-numeral}"
    typography: "{typography.numeral}"
    rounded: "{rounded.r-1}"
    padding: "0 4px"
    height: "22px"
  gate-cell-pass:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    height: "52px"
  gate-cell-fail:
    backgroundColor: "{colors.channel-red}"
    textColor: "{colors.on-channel}"
    height: "52px"
  gate-cell-warn:
    backgroundColor: "{colors.amber-wash}"
    textColor: "{colors.amber-text}"
    height: "52px"
  channel-sign-ok:
    backgroundColor: "{colors.channel-green}"
    textColor: "{colors.on-channel}"
    padding: "8px 20px"
    height: "46px"
  channel-sign-error:
    backgroundColor: "{colors.channel-red}"
    textColor: "{colors.on-channel}"
    padding: "8px 20px"
    height: "46px"
  channel-sign-warning:
    backgroundColor: "{colors.signage-yellow}"
    textColor: "{colors.sign-ink}"
    padding: "8px 20px"
    height: "46px"
  masthead:
    backgroundColor: "{colors.signage-yellow}"
    textColor: "{colors.sign-ink}"
    padding: "0 20px"
  select:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink}"
    rounded: "{rounded.r-1}"
    padding: "0 34px 0 12px"
    height: "38px"
  input-args:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink}"
    typography: "{typography.code-listing}"
    rounded: "{rounded.r-1}"
    padding: "8px 10px"
    height: "38px"
  segmented-on:
    backgroundColor: "{colors.mandatory-blue}"
    textColor: "{colors.on-channel}"
    rounded: "{rounded.micro}"
    padding: "0 12px"
    height: "30px"
  tab:
    backgroundColor: "transparent"
    textColor: "{colors.ink-2}"
    typography: "{typography.label}"
    padding: "0 6px"
    height: "40px"
  tab-active:
    textColor: "{colors.ink}"
  pane:
    backgroundColor: "{colors.panel}"
    rounded: "{rounded.r-2}"
  reading-sheet:
    backgroundColor: "{colors.panel}"
    typography: "{typography.body}"
    rounded: "{rounded.r-2}"
    padding: "34px 56px 44px"
  division-sign:
    textColor: "{colors.on-channel}"
    rounded: "{rounded.r-1}"
    padding: "0 10px"
    height: "26px"
---

# Design System: AgentScript

## Overview

**Creative North Star: "The Arrivals Hall"**

AgentScript is signed like a terminal building. A programme walks ten fixed gates and leaves by one of two customs channels: green when there is nothing to declare, red with the exact declaration (code, line:col, path). Two surfaces share the same world. The editor (Operate) and the docs site (Read) use the same yellow sign masthead, black numeral tiles, terminal-grey ground, white panels, and the same three channel colours. Each surface then sets its own density. The editor is a compact 15px instrument with fixed-height cells. The docs are a calm 17px reading sheet with a 33em measure.

The world owns the frame and the frame only. Signage colour sits at full strength in the masthead, the gate row, the channel sign, and the division tabs. Inside panes and the reading sheet, ink on white stays quiet, and colour returns only as washes on the lines that matter (the tainted line, the path step, the marked listing row). Pictograms are drawn strokes, never font glyphs or emoji. Numerals are tabular everywhere, so states can change in a cell without anything shifting.

Dark mode means lit signs on black. The ground and panels go near-black and neutral, the yellow sign stays exactly the same, and the channel colours shift a little so they keep their contrast. A sign does not change colour at night.

**Key Characteristics:**
- A signage-yellow masthead with black ink, on both surfaces, in both themes.
- A black numeral tile with a yellow numeral as the index mark for gates, stages, tabs and how-it-works pages.
- Ten equal, fixed gate cells. Only their state colour changes.
- One full-width channel sign carries the verdict: green, red, or yellow for warnings.
- Flat white panels on terminal grey, with one soft shadow and 3px/6px corners.
- Atkinson Hyperlegible Next for all UI and reading, and Atkinson Hyperlegible Mono for code and numerals.

## Colors

The palette is a wayfinding programme: one signage yellow, three channel hues with fixed meanings, and a cool grey-to-ink neutral ramp. All of it is declared once as custom properties in `:root` and in the two dark blocks of each stylesheet, with the same values on both surfaces.

### Primary
- **Signage Yellow** (`signage-yellow`): the masthead field, the numeral on black tiles, the text selection colour, the warning channel sign, and the "How it works" division. It never tints body text or panel fills.
- **Tile Black** (`tile-black`, `night-tile` in dark): numeral tiles, the Compile button, the docs primary button, toasts, and the "Presentation" division face.

### Secondary
- **Channel Green** (`channel-green`): the accepted verdict sign, the Run button, passed-gate ticks (as `channel-green-text`), the budget meter fill, and the "Start here" division. Its wash marks running or fixed lines.
- **Channel Red** (`channel-red`): the rejected verdict sign, the failed gate cell, error gutter marks and squiggles, and the docs taint gate. Its wash marks tainted lines and the rejected listing row.

### Tertiary
- **Mandatory Blue** (`mandatory-blue`): approval and opt-in. It covers the Approve segment, the Live tools switch, the approval gate on the docs landing page, and the "Specification" division. The `-text` step also carries links and the focus ring, and its wash marks the highlighted path step.
- **Amber** (`amber-wash`, `amber-text`, `amber-line`): warnings below the level of a sign, such as a warn gate cell, warning squiggles, the "edited, recompile" hint, and a full budget meter.

### Neutral
- **Terminal Grey** (`terminal-grey`; `night-ground` in dark): the ground under panes and around the reading sheet.
- **Panel / Panel 2** (`panel`, `panel-2`): white working surfaces, plus a one-step-down fill for gutters, code blocks, table heads, the run dock, and hover.
- **Rule / Rule Strong** (`rule`, `rule-strong`): 1px hairlines between cells and around panes. The strong step is for input borders, inset ghost strokes, and idle tiles.
- **Ink 1-3** (`ink`, `ink-2`, `ink-3`): primary text, secondary text, and tertiary or meta text (line numbers, idle gate labels).

### Named Rules
**The Fixed Channel Rule.** Green means accepted or run. Red means rejected or tainted. Blue means approval or opt-in. Yellow means the sign, or a warning. Never use a channel hue for decoration, and never give one a second meaning.

**The Lit Sign Rule.** Signage yellow and sign ink stay the same in dark mode. Only the ground, panels, rules, inks, tile black and channel steps take their `night-` values.

**The Index Hue Rule.** In the docs, a division hue appears at full strength only on its own sign: the rail division tab, the H1 chip or tile, the prev/next mini sign, and search-result chips. Hue never tints the reading column.

## Typography

**Display Font:** Atkinson Hyperlegible Next (with system-ui, -apple-system, Segoe UI, sans-serif)
**Body Font:** Atkinson Hyperlegible Next
**Label/Mono Font:** Atkinson Hyperlegible Mono (with ui-monospace, SFMono-Regular, Consolas, monospace)

**Character:** One legibility-first family in two widths. Hierarchy comes from heavy weights (700 and 800) and size, never from a second display face. The mono setting carries code, error codes, line:col positions and numerals.

### Hierarchy
- **Display** (800, clamp 2.1 to 2.75rem, 1.1): the docs landing H1 only. Doc page H1s use 2.4rem/1.12 with -0.02em tracking (2rem below 860px).
- **Headline** (700 to 800, 1.6rem, 1.2): doc H2s, which sit on a top hairline, and landing section heads.
- **Title** (800, 19px, -0.01em): editor panel titles. Pane titles and section titles use 15px/800, and the verdict status uses 16px/800.
- **Body** (400, 17px, 1.65, 33em measure): the docs reading sheet. The editor UI body is 15px/1.45 with tabular numerals.
- **Label** (700, 14px): gate names, tabs, field labels (13px), and masthead links (15px).
- **Code** (Mono 400, 16px, 1.6): the editor source. The user can step it with A- and A+ through `--code-size`. Listings and terminal output use 13 to 14.5px.
- **Numeral** (Mono 700, 12.5px, tabular): numeral tiles. Gate tiles in the editor use UI 800 at 15px in a 28px square.

### Named Rules
**The Tabular Rule.** Every numeral (gate numbers, line:col, counts, budgets, table figures) is set tabular, so a changing value never shifts its neighbours.

**The Weight Not Face Rule.** Emphasis steps from 400 to 700 to 800 within Atkinson Hyperlegible. Add no other display or serif face.

## Layout

The editor is a fixed-viewport instrument. The body is a four-row grid (masthead, gate row, channel sign, workspace) at 100dvh. The workspace holds two panes, source and output, in a 1fr to 1.08fr split with a 14px gutter and 14px padding. The run controls dock under the editor. The gate row is ten equal columns of 52px cells. Below 1080px the page becomes a scrolling document, the panes stack, and the gates wrap to 5 by 2. At 720px and below, the gate cells center their tile over their name at 64px tall, and the masthead wraps the example picker onto its own row.

The docs are a three-column layout capped at 1520px: a 276px sticky rail, the main column, and a 236px sticky table of contents. The TOC drops out at 1240px. At 860px the rail becomes an off-canvas drawer under a scrim. The reading sheet caps at 940px (1100px on wide pages and the landing page). The landing gate row uses the same ten equal columns, wraps to 5 by 2 at 1240px and to 2 columns at 560px, and the channel pair stacks at 980px.

The spacing rhythm is small and practical. It uses 4, 8, 12 and 14px inside components, and 20px for the masthead inset and the rail inset. Breakpoints are 1500, 1360, 1280, 1080, 720 and 480px in the editor, and 1240, 980, 860 and 560px in the docs.

**The Fixed Cells Rule.** Gates never move, resize, or reorder when state changes. Only colour and the trailing icon change. A stale result fades the row to 0.5 opacity and leaves it in place.

## Elevation & Depth

The system is flat and tonal. Depth comes from white panels on terminal grey and from hairline rules. One soft shadow lifts panes, the reading sheet, the docs gate row, the channel cards and the active rail or TOC item. A deeper shadow is used only for floating things that sit above the page (toasts, search results, the mobile drawer).

### Shadow Vocabulary
- **Rest** (`box-shadow: 0 1px 2px #16181d14, 0 2px 6px #16181d0f`; dark `0 1px 2px #00000066, 0 2px 8px #0000004d`): panes, the sheet, and the active nav item.
- **Float** (`box-shadow: 0 8px 28px #16181d29`; dark `0 10px 32px #000000a0`): toasts. The docs search popover stacks Rest with `0 12px 32px rgba(22,24,29,.16)`.

### Named Rules
**The Flat Sign Rule.** Signs (masthead, gate cells, channel sign, division tabs, tiles) carry no shadow. Hard offset shadows are not part of this world.

## Shapes

Corners are nearly square, like enamel sign plates. Small parts (tiles, buttons, inputs, signs, links) take 3px. Containers (panes, the sheet, code blocks, tables, gate cards) take 6px. Pills, kbd keys, segmented options and marker squares take 2px. The only full rounds are the toggle switch track and thumb and the spinner. Edges are 1px rules. Inset strokes (1.5px for ghost buttons and skipped tiles) draw an outline without changing the box size. Pictograms are drawn strokes that inherit `currentColor`.

## Components

### Buttons
Heavy, square-cornered and labelled, with keyboard shortcuts shown beside the label.
- **Shape:** squared plate (3px).
- **Primary (Compile / docs primary):** tile black with a yellow label, weight 800 at 16px, 42px tall in the editor. The docs version is 700 at 15px, 40px tall.
- **Run:** channel green with a white label. On hover it mixes 16% toward black.
- **Ghost / docs secondary:** transparent or panel fill with a 1.5px inset rule-strong stroke (a 1px border in the docs). Hover fills `panel-2`, or the border goes to ink.
- **Press:** the button moves down 1px. Busy buttons drop to 0.75 opacity and show an inline spinner.

### Numeral Tile (signature)
A black square with a yellow numeral, tabular, 3px corners. It is the index mark for gates, tab groups (1-3, 4-6, 7-9, 10), how-it-works pages, and path steps. When a step is active it inverts (the docs active nav tile goes yellow on ink). The failed path step tile turns red.

### Gate Row (signature)
Ten equal cells divided by 1px rules. Each cell holds a numeral tile, the gate name, an optional error code (mono), and a trailing state icon. The states are idle (grey tile, ink-3 label), pass (black tile, green tick), warn (amber wash, yellow tile), fail (the whole cell turns red with a white tile and red numeral), and skipped (an outlined tile).

### Channel Sign (signature)
A full-width band under the gates with a stroke pictogram on a translucent plate, the verdict at 800 weight, and a right-aligned check of the expected result. Ok is green, error is red, and warning is yellow. A mismatch inverts the expected-result chip to white. In the docs, the same idea appears as a pair of channel cards with a coloured head over a real listing and a collapsible transcript.

### Inputs / Fields
- **Style:** panel fill, 1px rule-strong border, 3px corners, 38px tall. Argument fields are set in mono.
- **Sign variant:** the example picker in the masthead uses a 2px ink border on white at weight 600. The docs search is white on yellow with a 55% ink border.
- **Focus:** a 2 to 2.5px blue outline at a 2px offset. On the yellow masthead the outline switches to sign ink.
- **Error:** a red border with a 2px red-wash halo.

### Tabs and Segmented Controls
- **Tabs:** 40px tall, ink-2 labels at 700 weight, and a 3px ink underline (drawn as an inset shadow) on the active tab. Tabs are grouped by gate range under a small numeral tile.
- **Segmented:** a 3px-padded bordered track. The on state is mandatory blue in the editor (Approve). The docs example filter uses tile black and yellow.

### Navigation
- **Masthead:** the yellow sign. It holds the brand tile (an arrow pictogram in a black square), the product name at 800 weight, bold links, and outlined icon buttons that invert to black and yellow on hover.
- **Docs rail:** a division tab at full hue, then quiet links with a tile or marker square. The active link lifts onto a white panel with the Rest shadow.

### Diagnostics in Code
Wavy red or amber squiggles on a matching wash, square red gutter marks, triangular amber warning marks, a red wash on tainted lines, a blue wash on path lines, and an amber flash when jumping to a line.

## Do's and Don'ts

### Do:
- **Do** take every colour from the shared custom properties, and keep both stylesheets' `:root` and dark blocks value-for-value identical.
- **Do** put a numeral tile on anything that is one of the ten gates or a numbered page.
- **Do** keep the ten gate cells equal and fixed, and show state with colour plus an icon or code, never by moving the cells.
- **Do** draw pictograms as inline stroke SVG in `currentColor`.
- **Do** set numerals tabular, and set code, error codes and positions in Atkinson Hyperlegible Mono.
- **Do** keep the reading column at about 33em and let only the frame carry signage colour.

### Don't:
- **Don't** use green, red or blue for anything except accept/run, reject/taint and approval/opt-in.
- **Don't** change the yellow sign in dark mode.
- **Don't** use emoji or font-glyph icons as pictograms.
- **Don't** add shadows to signs, or hard offset shadows anywhere.
- **Don't** add a second display face, a serif, or decorative gradients.
- **Don't** add small uppercase kicker or eyebrow labels above headings. The division sign and the numeral tile already do the job of telling the reader where they are.
