"""Build docs/presentation/AgentScript.pptx (python-pptx; all diagrams are native shapes).

Run: python docs/presentation/build_deck.py   (needs `pip install python-pptx`)
Every compiler output on the slides was pasted from a real run of the CLI.
"""

from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

OUT = Path(__file__).with_name("AgentScript.pptx")

# palette: deep ink dominates, amber is the one sharp accent, green/red mean safe/rejected
INK = RGBColor(0x14, 0x17, 0x2E)
INK2 = RGBColor(0x23, 0x28, 0x4A)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
PAPER = RGBColor(0xF4, 0xF5, 0xF9)
LINE = RGBColor(0xD5, 0xD8, 0xE3)
TEXT = RGBColor(0x1F, 0x23, 0x3B)
MUTED = RGBColor(0x5E, 0x64, 0x80)
AMBER = RGBColor(0xF2, 0xA0, 0x1B)
AMBER_T = RGBColor(0xFD, 0xF1, 0xDC)
GREEN = RGBColor(0x1F, 0x9D, 0x6B)
GREEN_T = RGBColor(0xDF, 0xF4, 0xEA)
RED = RGBColor(0xD6, 0x3E, 0x47)
RED_T = RGBColor(0xFB, 0xE3, 0xE4)
CODE_BG = RGBColor(0x1C, 0x20, 0x3A)
CODE_FG = RGBColor(0xE6, 0xE8, 0xF2)

HEAD = "Arial"
BODY = "Arial"
MONO = "Courier New"

prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)
BLANK = prs.slide_layouts[6]
W, H = 13.333, 7.5
_counter = {"n": 0}


# ------------------------------------------------------------------ helpers


def new_slide(dark: bool = False, notes: str = ""):
    s = prs.slides.add_slide(BLANK)
    bg = s.background.fill
    bg.solid()
    bg.fore_color.rgb = INK if dark else WHITE
    if notes:
        s.notes_slide.notes_text_frame.text = notes
    _counter["n"] += 1
    if not dark:
        text(s, f"AgentScript  ·  {_counter['n']}", W - 2.9, H - 0.45, 2.4, 0.3, 10, MUTED, align=PP_ALIGN.RIGHT)
    return s


def text(slide, content, x, y, w, h, size=16, color=TEXT, bold=False, font=BODY,
         align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, italic=False, name=None):
    """content: str, or list of paragraphs; a paragraph is str or list of (text, opts) runs."""
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    if name:
        tb.name = name
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    paras = content if isinstance(content, list) else [content]
    for i, para in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        runs = para if isinstance(para, list) else [(para, {})]
        for run_text, opts in runs:
            r = p.add_run()
            r.text = run_text
            f = r.font
            f.name = opts.get("font", font)
            f.size = Pt(opts.get("size", size))
            f.bold = opts.get("bold", bold)
            f.italic = opts.get("italic", italic)
            f.color.rgb = opts.get("color", color)
        if isinstance(para, list) and para and para[0][1].get("space_after"):
            p.space_after = Pt(para[0][1]["space_after"])
    return tb


def bullets(slide, items, x, y, w, h, size=16, color=TEXT, gap=8):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    for i, item in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_after = Pt(gap)
        pPr = p._p.get_or_add_pPr()
        pPr.set("marL", str(Emu(Inches(0.25))))
        pPr.set("indent", str(-Emu(Inches(0.25))))
        bu = pPr.makeelement(qn("a:buChar"), {"char": "•"})
        pPr.append(bu)
        runs = item if isinstance(item, list) else [(item, {})]
        for run_text, opts in runs:
            r = p.add_run()
            r.text = run_text
            r.font.name = opts.get("font", BODY)
            r.font.size = Pt(opts.get("size", size))
            r.font.bold = opts.get("bold", False)
            r.font.color.rgb = opts.get("color", color)
    return tb


def box(slide, x, y, w, h, fill=PAPER, line=None, radius=True, dash=False, shadow=False, name=None):
    shp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE,
                                 Inches(x), Inches(y), Inches(w), Inches(h))
    if name:
        shp.name = name
    if radius:
        shp.adjustments[0] = min(0.18, 0.12 / max(min(w, h), 0.1) * 1.0)
    if fill is None:
        shp.fill.background()
    else:
        shp.fill.solid()
        shp.fill.fore_color.rgb = fill
    if line is None:
        shp.line.fill.background()
    else:
        shp.line.color.rgb = line
        shp.line.width = Pt(1.5)
        if dash:
            shp.line.dash_style = 7  # dash
    if not shadow:
        sppr = shp._element.spPr
        sppr.append(sppr.makeelement(qn("a:effectLst"), {}))
    shp.text_frame.text = ""
    return shp


def label_box(slide, label, x, y, w, h, fill=PAPER, color=TEXT, size=14, bold=True, line=None,
              dash=False, sub=None, sub_size=11, font=BODY, sub_color=None):
    shp = box(slide, x, y, w, h, fill=fill, line=line, dash=dash)
    tf = shp.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(0.08)
    tf.margin_top = tf.margin_bottom = Inches(0.04)
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = label
    r.font.name = font
    r.font.size = Pt(size)
    r.font.bold = bold
    r.font.color.rgb = color
    if sub:
        p2 = tf.add_paragraph()
        p2.alignment = PP_ALIGN.CENTER
        r2 = p2.add_run()
        r2.text = sub
        r2.font.name = BODY
        r2.font.size = Pt(sub_size)
        r2.font.color.rgb = sub_color or color
    return shp


def arrow(slide, x1, y1, x2, y2, color=MUTED, width=1.75, dash=False):
    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    c.line.color.rgb = color
    c.line.width = Pt(width)
    if dash:
        c.line.dash_style = 7
    ln = c.line._get_or_add_ln()
    ln.append(ln.makeelement(qn("a:tailEnd"), {"type": "triangle", "w": "med", "len": "med"}))
    return c


def code(slide, lines, x, y, w, h, size=12, title=None):
    box(slide, x, y, w, h, fill=CODE_BG)
    top = y + 0.18
    if title:
        text(slide, title, x + 0.25, y + 0.15, w - 0.5, 0.3, 11, AMBER, bold=True)
        top = y + 0.5
    paras = []
    for ln in lines:
        if isinstance(ln, tuple):
            paras.append([(ln[0], {"color": ln[1], "font": MONO, "size": size})])
        else:
            paras.append([(ln, {"color": CODE_FG, "font": MONO, "size": size})])
    text(slide, paras, x + 0.25, top, w - 0.5, h - (top - y) - 0.15, size, CODE_FG, font=MONO)


def title(slide, t, kicker=None, dark=False):
    if kicker:
        text(slide, kicker.upper(), 0.6, 0.42, 9, 0.3, 12, AMBER, bold=True)
    text(slide, t, 0.6, 0.72, 12.1, 0.75, 32, WHITE if dark else TEXT, bold=True, font=HEAD)


def icon_circle(slide, glyph, x, y, d=0.62, fill=AMBER, color=INK, size=20):
    c = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x), Inches(y), Inches(d), Inches(d))
    c.fill.solid()
    c.fill.fore_color.rgb = fill
    c.line.fill.background()
    tf = c.text_frame
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = glyph
    r.font.size = Pt(size)
    r.font.bold = True
    r.font.name = HEAD
    r.font.color.rgb = color
    return c


def table(slide, rows, x, y, w, col_w, row_h=0.36, size=12, header_fill=INK, mono_cols=()):
    shp = slide.shapes.add_table(len(rows), len(rows[0]), Inches(x), Inches(y), Inches(w), Inches(row_h * len(rows)))
    tbl = shp.table
    for i, cw in enumerate(col_w):
        tbl.columns[i].width = Inches(cw)
    for r, row in enumerate(rows):
        tbl.rows[r].height = Inches(row_h)
        for c, val in enumerate(row):
            cell = tbl.cell(r, c)
            cell.margin_left = cell.margin_right = Inches(0.08)
            cell.margin_top = cell.margin_bottom = Inches(0.03)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.fill.solid()
            cell.fill.fore_color.rgb = header_fill if r == 0 else (WHITE if r % 2 else PAPER)
            tf = cell.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            color = None
            if isinstance(val, tuple):
                val, color = val
            run = p.add_run()
            run.text = val
            run.font.size = Pt(size)
            run.font.name = MONO if (c in mono_cols and r > 0) else BODY
            run.font.bold = r == 0
            run.font.color.rgb = WHITE if r == 0 else (color or TEXT)
    return shp


# ------------------------------------------------------------------ slides

# 1. title
s = new_slide(dark=True, notes="AgentScript: a tiny language whose compiler refuses unsafe AI-agent programs before they run.")
text(s, "COMPILER LAB PROJECT", 0.8, 1.55, 8, 0.4, 14, AMBER, bold=True)
text(s, "AgentScript", 0.8, 2.0, 8, 1.2, 60, WHITE, bold=True, font=HEAD)
text(s, "A tiny language and compiler that rejects unsafe AI-agent programs before they run",
     0.8, 3.25, 6.6, 1.0, 22, RGBColor(0xC9, 0xCD, 0xE0))
text(s, "Taint tracking  ·  Approval-path checking  ·  Call budgets  ·  10-stage pipeline  ·  Web editor",
     0.8, 4.65, 7.0, 0.6, 14, RGBColor(0x9A, 0xA0, 0xC0))
# motif preview: the pipeline as chips
stages = ["Lexer", "Parser", "Semantic", "IR + CFG", "Taint", "Approval", "Optimizer", "Scheduler", "Codegen", "VM"]
for i, st in enumerate(stages):
    yy = 1.0 + i * 0.53
    safe = st in ("Taint", "Approval")
    label_box(s, st, 9.6, yy, 2.9, 0.42, fill=AMBER if safe else INK2,
              color=INK if safe else WHITE, size=13, line=None, dash=False)
    if i < len(stages) - 1:
        arrow(s, 11.05, yy + 0.42, 11.05, yy + 0.53, color=RGBColor(0x6B, 0x72, 0x9A), width=1.25)

# 2. problem
s = new_slide(notes="Agent frameworks check safety at runtime, if at all. Three failure modes matter most.")
title(s, "Agents fail after the tool has already fired", "The problem")
cards = [
    ("!", "Prompt injection", "Text fetched from the web or a file carries instructions, and the agent pipes it into send_email or run_shell.", RED, RED_T),
    ("X", "Irreversible actions", "The agent deletes a file without asking a human first. There is no undo.", AMBER, AMBER_T),
    ("∞", "Unbounded tool use", "The agent loops or repeats identical calls, wasting money and hitting rate limits.", INK2, PAPER),
]
for i, (g, h, b, col, tint) in enumerate(cards):
    x = 0.6 + i * 4.1
    box(s, x, 1.9, 3.8, 3.6, fill=tint)
    icon_circle(s, g, x + 0.35, 2.2, fill=col, color=WHITE, size=22)
    text(s, h, x + 0.35, 3.05, 3.2, 0.5, 20, TEXT, bold=True)
    text(s, b, x + 0.35, 3.6, 3.15, 1.7, 15, MUTED)
text(s, [[("Idea: ", {"bold": True, "color": TEXT}),
          ("a compiler can catch the first two with data-flow and control-flow analysis, and limit the third with permits, budgets and duplicate-call elimination, before anything runs.", {"color": TEXT})]],
     0.6, 5.85, 12.1, 0.8, 16)

# 3. guarantees
s = new_slide(notes="Two headline guarantees, plus permissions and budgets.")
title(s, "Two guarantees, proven at compile time", "What the compiler proves")
g = [
    ("1", "No unsanitized injection", "Untrusted data (web_search, read_file) never reaches a privileged tool (send_email, delete_file) unless it passes through sanitize.", "E401 · forward data-flow taint analysis on the CFG", GREEN),
    ("2", "No unapproved irreversible action", "Every delete_file call is dominated by the true branch of a confirm(...) result.", "E501 / E502 · dominator analysis on the CFG", GREEN),
]
for i, (n, h, b, how, col) in enumerate(g):
    x = 0.6 + i * 6.15
    box(s, x, 1.85, 5.9, 2.9, fill=GREEN_T)
    icon_circle(s, n, x + 0.35, 2.15, fill=col, color=WHITE)
    text(s, h, x + 1.15, 2.22, 4.5, 0.5, 20, TEXT, bold=True)
    text(s, b, x + 0.35, 2.95, 5.2, 1.1, 15, TEXT)
    text(s, how, x + 0.35, 4.15, 5.3, 0.4, 13, GREEN, bold=True)
extras = [("permit", "Calling a tool outside the permit list is E305"),
          ("budget", "Worst-path call count above the budget is E306; the VM re-checks at runtime (E601)"),
          ("types", "Scoped symbol table and type checker (E301 to E304)")]
for i, (k, v) in enumerate(extras):
    x = 0.6 + i * 4.1
    box(s, x, 5.05, 3.8, 1.55, fill=PAPER)
    text(s, k, x + 0.3, 5.22, 3.2, 0.4, 16, AMBER, bold=True, font=MONO)
    text(s, v, x + 0.3, 5.62, 3.25, 0.9, 13, MUTED)

# 4. language
s = new_slide(notes="The PRD's example, line by line: permit list, budget, a task, search, sanitize, summarize, confirm, send.")
title(s, "The language: agents, permits, budgets, tasks", "AgentScript in one program")
code(s, [
    ("agent Assistant {", CODE_FG),
    ("  permit web_search, llm, sanitize,", AMBER),
    ("         send_email, confirm;", AMBER),
    ("  budget calls = 5;", AMBER),
    "",
    "  task report(topic: string) -> bool {",
    ("    let raw = web_search(topic);", RGBColor(0xFF, 0x9A, 0x9F)),
    ("    let clean = sanitize(raw[0]);", RGBColor(0x8F, 0xE3, 0xBC)),
    "    let summary = llm(\"Summarize: \" + clean);",
    ("    if (confirm(\"Send report?\")) {", RGBColor(0x8F, 0xE3, 0xBC)),
    "      return send_email(\"me@example.com\", summary);",
    "    }",
    "    return false;",
    "  }",
    "}",
], 0.6, 1.75, 7.1, 4.95, size=14, title="examples/valid_report.as")
notes_ = [
    ("permit / budget", "which tools the agent may call, and how many calls one task run may make"),
    ("web_search", "returns untrusted data: a taint source"),
    ("sanitize", "clears taint; its output is trusted"),
    ("confirm", "human approval; branching on it creates a guard block"),
    ("Types", "string, int, bool, list<T>; let is immutable, plus one bounded loop: repeat N { }"),
]
for i, (k, v) in enumerate(notes_):
    y = 1.8 + i * 0.98
    text(s, k, 8.1, y, 4.6, 0.35, 15, TEXT, bold=True)
    text(s, v, 8.1, y + 0.36, 4.6, 0.6, 13, MUTED)

# 5. tool table
s = new_slide(notes="Annotations are a fixed built-in table, not syntax. Each flag drives one analysis.")
title(s, "Built-in tools and their safety annotations", "A fixed table, not user syntax")
Y, N = ("yes", GREEN), ""
rows = [
    ["Tool", "Signature", "Untrusted result", "Propagates", "Sanitizer", "Privileged sink", "Irreversible", "Approval", "Mergeable"],
    ["web_search", "string -> list<string>", Y, N, N, N, N, N, Y],
    ["read_file", "string -> string", Y, N, N, N, N, N, Y],
    ["llm", "string -> string", N, Y, N, N, N, N, Y],
    ["send_email", "(string, string) -> bool", N, N, N, Y, N, N, N],
    ["delete_file", "string -> bool", N, N, N, Y, Y, N, N],
    ["sanitize", "string -> string", N, N, Y, N, N, N, Y],
    ["confirm", "string -> bool", N, N, N, N, N, Y, N],
]
table(s, rows, 0.6, 1.8, 12.1, [1.45, 2.45, 1.3, 1.1, 1.05, 1.35, 1.2, 1.0, 1.2], row_h=0.45, size=13, mono_cols=(0, 1))
text(s, [[("Used by:  ", {"bold": True}),
          ("taint analysis (untrusted, propagates, sanitizer, privileged)  ·  approval analysis (irreversible, approval)  ·  optimizer (mergeable)  ·  scheduler (privileged, irreversible and approval tools are barriers)", {})]],
     0.6, 5.65, 12.1, 0.8, 14, MUTED)

# 6. pipeline diagram
s = new_slide(notes="Ten stages. Each hands a printable artifact (text + JSON) to the next; the editor shows every one. Safety analyses run before optimization.")
title(s, "Architecture: a 10-stage pipeline", "Compiler architecture")
row1 = [("Lexer", "source -> tokens", "E101 E102"), ("Parser", "tokens -> AST", "E201"),
        ("Semantic", "symbols, types, permit, budget", "E301-E306"), ("IR + CFG", "3-address code, blocks", ""),
        ("Taint", "data-flow fixed point", "E401")]
row2 = [("Approval", "dominators, guards", "E501 E502"), ("Optimizer", "fold, DCE, dedupe calls", ""),
        ("Scheduler", "parallel rounds (stretch)", ""), ("Codegen", "IR -> stack bytecode", ""),
        ("VM", "tool registry, guards", "E601-E604")]
bw, bh, gap = 2.12, 1.25, 0.37
for r, row in enumerate((row1, row2)):
    y = 1.95 + r * 2.15
    for i, (name, what, codes) in enumerate(row):
        x = 0.6 + i * (bw + gap)
        safety = name in ("Taint", "Approval")
        stretch = name == "Scheduler"
        label_box(s, name, x, y, bw, bh, fill=AMBER_T if safety else PAPER,
                  line=AMBER if safety else (MUTED if stretch else None), dash=stretch,
                  sub=what, size=16, sub_size=12, sub_color=MUTED)
        if codes:
            text(s, codes, x, y + bh + 0.08, bw, 0.3, 11, RED, bold=True, align=PP_ALIGN.CENTER, font=MONO)
        if i < 4:
            arrow(s, x + bw + 0.04, y + bh / 2, x + bw + gap - 0.04, y + bh / 2)
# wrap arrow from Taint (row1 end) down to Approval (row2 start)
arrow(s, 0.6 + 4 * (bw + gap) + bw / 2, 1.95 + bh + 0.42, 0.6 + 4 * (bw + gap) + bw / 2, 1.95 + bh + 0.62, color=MUTED)
arrow(s, 0.6 + 4 * (bw + gap) + bw / 2 - 0.05, 3.85, 0.6 + bw / 2 + 0.05, 3.85, color=MUTED)
arrow(s, 0.6 + bw / 2, 3.85, 0.6 + bw / 2, 4.08, color=MUTED)
box(s, 0.6, 6.0, 12.1, 0.72, fill=INK)
text(s, [[("Ordering rule  ", {"bold": True, "color": AMBER}),
          ("Safety analyses (permission, budget, taint, approval) run on the unoptimized program, so a guarantee never depends on what the optimizer removes.", {"color": WHITE})]],
     0.85, 6.1, 11.6, 0.55, 14, WHITE, anchor=MSO_ANCHOR.MIDDLE)

# 7. system architecture
s = new_slide(notes="Front end, middle end, back end as Python modules; the editor and CLI drive the same pipeline.")
title(s, "System architecture: modules and data flow", "How the code is organised")
cols = [
    ("Front end", ["lexer.py", "parser.py", "ast_nodes.py", "semantic.py"], "Tokens · AST · Symbols"),
    ("Middle end", ["irgen.py", "cfg.py", "taint.py", "approval.py", "optimizer.py", "scheduler.py"], "IR · CFG · Reports"),
    ("Back end", ["codegen.py", "bytecode.py", "vm.py", "registry.py"], "Bytecode · Call log"),
]
for i, (h, mods, out) in enumerate(cols):
    x = 0.6 + i * 3.0
    box(s, x, 1.85, 2.7, 4.2, fill=PAPER)
    text(s, h, x + 0.25, 2.0, 2.2, 0.4, 17, TEXT, bold=True)
    for j, m in enumerate(mods):
        label_box(s, m, x + 0.25, 2.5 + j * 0.47, 2.2, 0.38, fill=WHITE, color=TEXT, size=12, bold=False, font=MONO)
    text(s, out, x + 0.25, 5.55, 2.3, 0.35, 12, AMBER, bold=True)
    if i < 2:
        arrow(s, x + 2.72, 3.95, x + 2.98, 3.95)
label_box(s, "pipeline.py", 9.75, 1.85, 2.95, 0.75, fill=INK, color=WHITE, size=15, font=MONO,
          sub="compile_source · run_source", sub_size=11, sub_color=AMBER)
label_box(s, "api.py  (FastAPI)", 9.75, 3.05, 2.95, 0.75, fill=INK2, color=WHITE, size=14, font=MONO,
          sub="/compile  /run  /examples", sub_size=11, sub_color=RGBColor(0xC9, 0xCD, 0xE0))
label_box(s, "web/  editor", 9.75, 4.25, 2.95, 0.75, fill=AMBER_T, color=TEXT, size=14, font=MONO,
          sub="CodeMirror · Mermaid · tabs", sub_size=11, sub_color=MUTED)
label_box(s, "__main__.py  CLI", 9.75, 5.3, 2.95, 0.75, fill=PAPER, color=TEXT, size=14, font=MONO,
          sub="compile · run · serve", sub_size=11, sub_color=MUTED)
arrow(s, 11.22, 3.05, 11.22, 2.62)
arrow(s, 11.22, 4.25, 11.22, 3.82)
arrow(s, 9.73, 2.22, 9.0, 2.22, color=MUTED)
text(s, "Shared: diagnostics.py (one diagnostic format for CLI, API and squiggles) · tools.py (annotation table) · ir.py",
     0.6, 6.3, 12.1, 0.4, 13, MUTED)

# 8. front end
s = new_slide(notes="Hand-written scanner, recursive descent parser with one function per rule, scoped symbol table and type checker.")
title(s, "Front end: lexer, parser, semantic analysis", "Stages 1 to 3")
code(s, [
    ("program   = \"agent\" IDENT \"{\" { permit } budget task { task } \"}\" ;", CODE_FG),
    ("statement = let | if | repeat | return | expr \";\" ;", CODE_FG),
    ("repeat    = \"repeat\" ( INT | IDENT ) block ;", AMBER),
    ("equality  = relational { (\"==\" | \"!=\") relational } ;", CODE_FG),
    ("additive  = term { (\"+\" | \"-\") term } ;", CODE_FG),
    ("postfix   = primary { \"[\" expr \"]\" } ;", CODE_FG),
], 0.6, 1.75, 12.1, 2.15, size=13, title="Grammar excerpt (full EBNF in docs/PRD.md)")
rows = [
    ["Code", "Phase", "Demo program", "Real diagnostic"],
    ["E101", "lexer", "lex_unterminated.as", "6:13  unterminated string: missing closing '\"' before end of line"],
    ["E201", "parser", "syntax_missing_semicolon.as", "6:30  expected ';', found 'return'"],
    ["E301", "semantic", "sem_undeclared.as", "6:12  undeclared variable 'x'"],
    ["E303", "semantic", "sem_type_mismatch.as", "6:23  argument 1 of web_search must be string, found int"],
    ["E305", "semantic", "sem_not_permitted.as", "6:16  tool 'read_file' is not permitted; add it to a permit declaration"],
    ["E306", "semantic", "sem_budget.as", "9:12  task 'dig' may make 4 tool calls on its worst path, but the budget is 3"],
]
table(s, rows, 0.6, 4.15, 12.1, [0.9, 1.15, 3.25, 6.8], row_h=0.38, size=11, mono_cols=(0, 2))

# 9. IR and CFG
s = new_slide(notes="Three-address code, split into basic blocks. The block after the confirm branch's true edge is the guard block.")
title(s, "IR and control-flow graph", "Stage 4")
code(s, [
    "task report(topic: string) -> bool",
    "    raw = call web_search(topic)",
    "    t1 = raw[0]",
    "    clean = call sanitize(t1)",
    "    t2 = \"Summarize: \" + clean",
    "    summary = call llm(t2)",
    "    t3 = call confirm(\"Send report?\")",
    "    if t3 goto L1 else L2",
    ("  L1:", AMBER),
    "    t4 = call send_email(\"me@...\", summary)",
    "    return t4",
    ("  L2:", AMBER),
    "    return false",
], 0.6, 1.75, 6.2, 4.95, size=13, title="compile --phase ir  (valid_report.as, real output)")
label_box(s, "entry", 8.15, 1.85, 3.9, 1.55, fill=PAPER, size=15,
          sub="raw = web_search · t1 = raw[0] · clean = sanitize · summary = llm · t3 = confirm · if t3",
          sub_size=11, sub_color=MUTED)
label_box(s, "L1  (guard block)", 7.3, 4.25, 2.6, 1.15, fill=GREEN_T, line=GREEN, size=14,
          sub="t4 = send_email · return t4", sub_size=11, sub_color=MUTED)
label_box(s, "L2", 10.35, 4.25, 2.35, 1.15, fill=PAPER, size=14, sub="return false", sub_size=11, sub_color=MUTED)
arrow(s, 9.3, 3.42, 8.6, 4.22, color=GREEN, width=2)
arrow(s, 10.9, 3.42, 11.5, 4.22, color=RED, width=2)
text(s, "T", 8.6, 3.6, 0.4, 0.3, 13, GREEN, bold=True)
text(s, "F", 11.45, 3.6, 0.4, 0.3, 13, RED, bold=True)
text(s, "Temps t1..tn and labels L1..Ln are numbered per task; every block ends in exactly one jump, branch or return.",
     7.3, 5.7, 5.4, 0.9, 13, MUTED)

# 10. taint
s = new_slide(notes="Headline feature 1. Remove sanitize and the search result flows through llm into send_email: rejected with the full path.")
title(s, "Taint analysis catches the prompt injection", "Headline feature 1 · stage 5")
chain = [("web_search(topic)", "source: untrusted", RED_T, RED), ("raw[0]", "index keeps taint", RED_T, RED),
         ("\"Summarize: \" + ...", "concat joins taint", RED_T, RED), ("llm(...)", "result inherits taint", RED_T, RED),
         ("send_email(.., summary)", "privileged sink", RED, RED)]
for i, (lbl, sub, fill, ln) in enumerate(chain):
    x = 0.6 + i * 2.45
    last = i == len(chain) - 1
    label_box(s, lbl, x, 1.85, 2.15, 1.05, fill=fill, line=None, color=WHITE if last else TEXT, size=13,
              font=MONO, sub=sub, sub_size=11, sub_color=WHITE if last else MUTED)
    if not last:
        arrow(s, x + 2.17, 2.37, x + 2.43, 2.37, color=RED, width=2)
code(s, [
    ("E401 [taint] 9:14: untrusted data from web_search (line 6) reaches", RGBColor(0xFF, 0x9A, 0x9F)),
    ("  privileged tool 'send_email' (line 9), argument 2; pass it through sanitize first", RGBColor(0xFF, 0x9A, 0x9F)),
    "    6:15  raw = call web_search(topic)  <- web_search returns untrusted data",
    "    7:42  t1 = raw[0]",
    "    7:37  t2 = \"Summarize: \" + t1",
    "    7:19  summary = call llm(t2)",
    "    9:14  t4 = call send_email(\"me@example.com\", summary)  <- privileged sink",
], 0.6, 3.25, 12.1, 2.55, size=12, title="compile examples/taint_injection.as  (real output)")
text(s, [[("Rule: ", {"bold": True, "color": TEXT}),
          ("forward data-flow over the CFG to a fixed point; labels trusted < untrusted; params and literals trusted; sanitize is the only way back to trusted. With sanitize(raw[0]) in place, valid_report.as compiles.", {"color": MUTED})]],
     0.6, 6.0, 12.1, 0.75, 14)

# 11. approval
s = new_slide(notes="Headline feature 2. Dominance by the confirm call is not enough because confirm can return false; the call must be dominated by the TRUE successor.")
title(s, "Approval analysis: deletes need a dominating confirm", "Headline feature 2 · stage 6")
label_box(s, "entry", 1.95, 1.85, 2.4, 0.7, fill=PAPER, size=14, sub="if (force)", sub_size=11, sub_color=MUTED)
label_box(s, "L1: delete_file(path)", 0.6, 3.25, 2.55, 0.85, fill=RED_T, line=RED, size=12, font=MONO,
          sub="no confirm on this path", sub_size=11, sub_color=RED)
label_box(s, "if (confirm(...))", 3.35, 3.25, 2.45, 0.85, fill=PAPER, size=12, font=MONO)
label_box(s, "guard: delete_file", 3.35, 4.65, 2.45, 0.85, fill=GREEN_T, line=GREEN, size=12, font=MONO,
          sub="dominated by the true edge", sub_size=11, sub_color=GREEN)
arrow(s, 2.6, 2.57, 1.9, 3.22, color=RED, width=2)
arrow(s, 3.7, 2.57, 4.5, 3.22, color=MUTED, width=2)
arrow(s, 4.57, 4.12, 4.57, 4.62, color=GREEN, width=2)
text(s, "force = true", 0.7, 2.7, 1.5, 0.3, 11, RED, bold=True)
text(s, "T", 4.7, 4.2, 0.3, 0.3, 12, GREEN, bold=True)
code(s, [
    ("E501 [approval] 7:14: irreversible call to 'delete_file' (line 7)", RGBColor(0xFF, 0x9A, 0x9F)),
    ("  is reachable without confirm", RGBColor(0xFF, 0x9A, 0x9F)),
    "    6:5   task purge starts (entry)",
    "    6:5   line 6: if force -> true (L1)",
    "    7:14  delete_file(...) is irreversible and not guarded",
    "",
    ("E502 [approval] 9:12: ... not guarded by confirm on every", RGBColor(0xFF, 0x9A, 0x9F)),
    ("  path; the confirm on line 7 does not guard it", RGBColor(0xFF, 0x9A, 0x9F)),
    "    6:5   line 6: if careful -> false (L2)",
], 6.25, 1.75, 6.45, 3.85, size=11, title="approval_missing.as  /  approval_one_branch.as  (real output)")
text(s, [[("Rule: ", {"bold": True, "color": TEXT}),
          ("a guard block is the true successor of a branch on a confirm value (if (confirm(..)) or let ok = confirm(..); if (ok)). Each irreversible call must sit in a block dominated by a guard. Dominators: simple iterative algorithm.", {"color": MUTED})]],
     0.6, 5.85, 12.1, 0.9, 14)

# 12. optimizer
s = new_slide(notes="Runs only after every safety check passes. optimize_demo.as: 14 -> 10 instructions, 4 -> 2 tool calls.")
title(s, "Optimizer: fewer instructions, fewer paid calls", "Stage 7")
for i, (big, lbl) in enumerate([("14 → 10", "IR instructions"), ("4 → 2", "tool calls")]):
    x = 0.6 + i * 3.1
    box(s, x, 1.85, 2.85, 2.0, fill=AMBER_T)
    text(s, big, x, 2.05, 2.85, 1.0, 44, INK, bold=True, align=PP_ALIGN.CENTER, font=HEAD)
    text(s, lbl, x, 3.1, 2.85, 0.4, 15, MUTED, align=PP_ALIGN.CENTER)
bullets(s, [
    [("Constant folding ", {"bold": True}), ("with local propagation; a branch on a constant becomes a jump", {})],
    [("Dead code elimination: ", {"bold": True}), ("unreachable blocks and unused assignments (never a Call or Index)", {})],
    [("Duplicate tool-call elimination: ", {"bold": True}), ("same read-only tool, same arguments, same block, no call in between; never confirm, send_email or delete_file", {})],
], 0.6, 4.15, 5.95, 2.6, size=14, gap=10)
code(s, [
    "instructions 14 -> 10, tool calls 4 -> 2",
    "changes:",
    "  line 6: folded pages = 2 * 3 -> 6",
    "  line 10: replaced debug with false",
    "  line 10: branch on false -> goto L2",
    "  removed unreachable block L1 (line 11)",
    "  line 6: removed dead assignment pages = 6",
    "  line 9: removed dead assignment debug = false",
    ("  line 8: duplicate call web_search(topic)", AMBER),
    ("          replaced by copy of first (line 7)", AMBER),
], 6.9, 1.75, 5.8, 4.95, size=12, title="compile optimize_demo.as --phase optimized_ir")

# 13. codegen + VM
s = new_slide(notes="Stack bytecode, a VM loop with runtime permission and budget guards, and a deterministic mock tool registry.")
title(s, "Code generation and the stack VM", "Stages 9 and 10")
code(s, [
    "   0  LOAD topic",
    "   1  CALL web_search 1",
    "   2  STORE raw",
    "   3  LOAD raw",
    "   4  PUSH_CONST 0",
    "   5  INDEX",
    "   6  STORE t1",
    "   7  LOAD t1",
    "   8  CALL sanitize 1",
    "   9  STORE clean",
    "  ...",
], 0.6, 1.75, 4.1, 4.95, size=13, title="--phase bytecode (valid_report)")
code(s, [
    "calls: 5 of budget 5, rounds: 5",
    " #  line  tool        result",
    " 1     6  web_search  [\"AI safety: IGNORE ALL ...",
    " 2     7  sanitize    \"... [removed instruction] ...",
    " 3     8  llm         \"[llm] Summarize: ...",
    " 4     9  confirm     true",
    " 5    10  send_email  true",
    ("value: true", RGBColor(0x8F, 0xE3, 0xBC)),
], 4.95, 1.75, 7.75, 3.0, size=12, title="run valid_report.as --task report  (real call log, trimmed)")
code(s, [
    ("E601 [runtime] 7:15: budget exceeded: call 4 would", RGBColor(0xFF, 0x9A, 0x9F)),
    ("  exceed the budget of 3 calls", RGBColor(0xFF, 0x9A, 0x9F)),
], 4.95, 4.95, 7.75, 1.05, size=12)
text(s, "runtime_budget.as: repeat times { web_search } compiles with warning W306, then the VM guard trips on call 4 when times = 5.",
     4.95, 6.15, 7.75, 0.6, 13, MUTED)

# 14. scheduler
s = new_slide(notes="Stretch goal M7, built. Independent calls in one basic block run concurrently; barrier tools are never reordered.")
title(s, "Parallel scheduling: 3 independent calls, 1 round", "Stage 8 · stretch goal (built)")
text(s, "Before: 4 rounds (one call each)", 0.6, 1.8, 5.5, 0.35, 15, TEXT, bold=True)
for i, c in enumerate(["web_search(a)", "web_search(b)", "web_search(c)", "llm(ra[1] + rb[1] + rc[1])"]):
    label_box(s, c, 0.6, 2.3 + i * 0.95, 4.6, 0.7, fill=PAPER, size=13, font=MONO, bold=False)
    if i < 3:
        arrow(s, 2.9, 3.0 + i * 0.95, 2.9, 3.25 + i * 0.95)
text(s, "After: 2 rounds", 6.4, 1.8, 6.0, 0.35, 15, TEXT, bold=True)
box(s, 6.4, 2.3, 6.3, 1.35, fill=AMBER_T)
text(s, "round 1", 6.6, 2.4, 2, 0.3, 12, AMBER, bold=True)
for i, c in enumerate(["web_search(a)", "web_search(b)", "web_search(c)"]):
    label_box(s, c, 6.6 + i * 2.0, 2.75, 1.85, 0.7, fill=WHITE, size=12, font=MONO, bold=False)
box(s, 6.4, 4.05, 6.3, 1.1, fill=PAPER)
text(s, "round 2", 6.6, 4.15, 2, 0.3, 12, MUTED, bold=True)
label_box(s, "llm(...)", 8.6, 4.45, 1.9, 0.55, fill=WHITE, size=12, font=MONO, bold=False)
arrow(s, 9.55, 3.67, 9.55, 4.42)
text(s, [[("Real output: ", {"bold": True, "color": TEXT}),
          ("task scout: rounds 4 -> 2;  round 1: ra = call web_search(a) | rb = call web_search(b) | rc = call web_search(c)", {"color": MUTED, "font": MONO, "size": 12})]],
     6.4, 5.35, 6.3, 0.9, 13)
text(s, "Dependency graph per basic block; send_email, delete_file and confirm are barriers, so they are never reordered (L3).",
     0.6, 6.25, 12.1, 0.5, 13, MUTED)

# 15. editor + API
s = new_slide(notes="One static page, CodeMirror and Mermaid from a CDN, FastAPI backend. A Compile click runs every phase and fills every tab.")
title(s, "Web editor and API: one click runs every phase", "Editor and demo experience")
steps = [("Browser", "CodeMirror editor, example picker, Compile / Run"), ("POST /compile", "FastAPI (api.py)"),
         ("compile_source", "10 stages, one artifact each {text, data}"), ("JSON response", "phases, diagnostics, stats, tasks"),
         ("Tabs + squiggles", "errors underlined at line:col, CFG drawn with Mermaid")]
for i, (h, sub) in enumerate(steps):
    x = 0.6 + i * 2.48
    label_box(s, h, x, 1.9, 2.2, 1.45, fill=AMBER_T if i in (0, 4) else PAPER, size=14,
              sub=sub, sub_size=11, sub_color=MUTED)
    if i < 4:
        arrow(s, x + 2.22, 2.62, x + 2.46, 2.62)
tabs = ["Errors", "Tokens", "AST", "Symbols", "IR", "CFG", "Taint", "Approval", "Optimized IR", "Rounds", "Bytecode", "Output"]
text(s, "Phase tabs", 0.6, 3.75, 4, 0.35, 15, TEXT, bold=True)
for i, t in enumerate(tabs):
    x = 0.6 + (i % 6) * 2.03
    y = 4.2 + (i // 6) * 0.6
    label_box(s, t, x, y, 1.85, 0.45, fill=INK if t in ("Taint", "Approval") else PAPER,
              color=WHITE if t in ("Taint", "Approval") else TEXT, size=12, bold=False)
bullets(s, [
    "Pipeline strip colours each of the 10 stages pass / fail / warn; the failing stage shows its error code",
    "Run panel: task picker, JSON args, confirm approve/deny, live toggle (no API key needed: llm falls back to the mock)",
], 0.6, 5.55, 12.1, 1.2, size=14, gap=6)

# 16. error taxonomy
s = new_slide(notes="Every phase owns a class of errors; each has its own failing demo program in examples/.")
title(s, "Every phase catches its own mistakes", "Error taxonomy")
rows = [
    ["Code", "Phase", "Error", "Demo file", "Line:col"],
    ["E101 / E102", "lexer", "unterminated string / illegal character", "lex_unterminated / lex_illegal_char", "6:13 / 6:15"],
    ["E201", "parser", "missing ';' or brace", "syntax_missing_semicolon", "6:30"],
    ["E301 / E302", "semantic", "undeclared / duplicate name", "sem_undeclared / sem_duplicate", "6:12 / 7:9"],
    ["E303 / E304", "semantic", "type mismatch / missing return", "sem_type_mismatch / sem_missing_return", "6:23 / 9:3"],
    ["E305 / E306", "semantic", "tool not permitted / budget exceeded", "sem_not_permitted / sem_budget", "6:16 / 9:12"],
    [("E401", RED), "taint", "untrusted data reaches privileged tool", "taint_injection", "9:14"],
    [("E501 / E502", RED), "approval", "no confirm / confirm on one branch only", "approval_missing / approval_one_branch", "7:14 / 9:12"],
    ["W306 + E601", "runtime", "runtime budget guard", "runtime_budget (times = 5)", "6:12 / 7:15"],
    ["E603", "runtime", "index out of range", "runtime_index", "7:19"],
]
table(s, rows, 0.6, 1.75, 12.1, [1.6, 1.25, 3.85, 4.1, 1.3], row_h=0.44, size=12, mono_cols=(0, 3, 4))
text(s, "Target was at least 8 distinct error types: 14 error codes have their own failing program (E602 and E604 are covered by tests).",
     0.6, 6.3, 12.1, 0.45, 13, MUTED)

# 17. testing + results
s = new_slide(notes="941 tests: unit tests per phase, golden tests for every example, negative tests for every error row, API and CLI tests.")
title(s, "Results: every metric met", "Testing")
stats = [("941", "tests passing"), ("10 / 10", "stages in the editor"), ("14", "error codes demoed"), ("18", "example programs")]
for i, (big, lbl) in enumerate(stats):
    x = 0.6 + i * 1.62
    y = 1.85 if i < 2 else 3.75
    x = 0.6 + (i % 2) * 2.75
    box(s, x, y, 2.55, 1.7, fill=AMBER_T if i == 0 else PAPER)
    text(s, big, x, y + 0.2, 2.55, 0.85, 36, INK, bold=True, align=PP_ALIGN.CENTER, font=HEAD)
    text(s, lbl, x, y + 1.08, 2.55, 0.4, 13, MUTED, align=PP_ALIGN.CENTER)
counts = [("parser", 107), ("semantic", 105), ("pipeline", 105), ("vm", 97), ("lexer", 74), ("optimizer", 61),
          ("codegen", 55), ("irgen", 48), ("approval", 44), ("taint", 43), ("cfg", 43), ("scheduler", 41),
          ("api", 39), ("golden", 37), ("cli", 27), ("registry", 26)]
cd = CategoryChartData()
cd.categories = [c for c, _ in counts]
cd.add_series("tests", [n for _, n in counts])
gf = s.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, Inches(6.3), Inches(1.7), Inches(6.4), Inches(5.0), cd)
ch = gf.chart
ch.has_legend = False
ch.has_title = True
ch.chart_title.text_frame.text = "Tests per file (pytest --co)"
ch.chart_title.text_frame.paragraphs[0].runs[0].font.size = Pt(13)
ch.chart_title.text_frame.paragraphs[0].runs[0].font.color.rgb = TEXT
plot = ch.plots[0]
plot.gap_width = 45
plot.has_data_labels = True
plot.data_labels.font.size = Pt(10)
plot.data_labels.font.color.rgb = MUTED
plot.data_labels.position = XL_LABEL_POSITION.OUTSIDE_END
ser = plot.series[0]
ser.format.fill.solid()
ser.format.fill.fore_color.rgb = INK2
cat = ch.category_axis
cat.reverse_order = True
cat.tick_labels.font.size = Pt(10)
cat.tick_labels.font.color.rgb = MUTED
cat.format.line.color.rgb = LINE
val = ch.value_axis
val.visible = False
val.has_major_gridlines = False
text(s, "Unit tests per phase · golden output for every example · one negative test per error row · optimizer before/after counts · API and CLI end to end",
     0.6, 5.7, 5.4, 1.0, 13, MUTED)

# 18. limitations
s = new_slide(notes="Documented limitations instead of a soundness proof; each has a viva answer in docs/presentation/viva-notes.md.")
title(s, "Limitations, stated openly", "Design trade-offs")
lim = [
    ("Taint", "Explicit flows only (no implicit flow through if); one label per list; parameters are trusted; the LLM may launder text, so llm output stays tainted until sanitize."),
    ("Approval", "One confirm must dominate the call: two confirms on two branches before a join are rejected; confirm(..) == true is not accepted."),
    ("Budget", "Exact for literal loop bounds; repeat over a variable gives warning W306 and is enforced by the VM."),
    ("Scope", "No error recovery (first syntax error only); mock tools by default; sanitize is trusted by definition."),
]
for i, (h, b) in enumerate(lim):
    x = 0.6 + (i % 2) * 6.15
    y = 1.85 + (i // 2) * 2.35
    box(s, x, y, 5.9, 2.1, fill=PAPER)
    icon_circle(s, h[0], x + 0.3, y + 0.3, d=0.55, fill=INK2, color=WHITE, size=16)
    text(s, h, x + 1.05, y + 0.36, 4.5, 0.45, 18, TEXT, bold=True)
    text(s, b, x + 0.3, y + 1.0, 5.35, 1.05, 13, MUTED)

# 19. demo + close
s = new_slide(dark=True, notes="Live demo order follows docs/presentation/demo-script.md.")
text(s, "LIVE DEMO", 0.8, 0.8, 6, 0.4, 14, AMBER, bold=True)
text(s, "Run it yourself", 0.8, 1.2, 8, 0.9, 40, WHITE, bold=True, font=HEAD)
code(s, [
    ("$ python -m venv .venv", CODE_FG),
    ("$ .venv/bin/pip install -r requirements.txt", CODE_FG),
    ("$ .venv/bin/pytest -q          # 941 passed", RGBColor(0x8F, 0xE3, 0xBC)),
    ("$ .venv/bin/python -m agentscript serve --port 8000", AMBER),
    ("  open http://127.0.0.1:8000", CODE_FG),
], 0.8, 2.35, 7.4, 1.75, size=14)
order = ["valid_report.as: run, 5 of 5 calls", "front-end errors: lex, syntax, semantic",
         "taint_injection.as: E401 with path", "approval examples: E501, E502",
         "optimize_demo.as: calls 4 -> 2", "parallel_demo.as: rounds 4 -> 2"]
for i, o in enumerate(order):
    y = 1.3 + i * 0.72
    icon_circle(s, str(i + 1), 8.9, y, d=0.48, fill=AMBER, color=INK, size=14)
    text(s, o, 9.55, y + 0.08, 3.4, 0.5, 14, WHITE)
text(s, "Docs: docs/README.md  ·  PRD: docs/PRD.md  ·  How it works: docs/how-it-works/",
     0.8, 4.4, 7.4, 0.4, 13, RGBColor(0x9A, 0xA0, 0xC0))
text(s, "Thank you  ·  Questions?", 0.8, 6.2, 8, 0.6, 24, WHITE, bold=True)

prs.save(OUT)
print(f"wrote {OUT} ({len(prs.slides.__iter__.__self__._sldIdLst)} slides)")
