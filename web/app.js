/* AgentScript web editor: one page, vanilla JS (ES2020), no build step.
 *
 * Talks to the same-origin API (GET /examples, POST /compile, POST /run; brief section 7)
 * and shows every phase artifact in its own tab. CodeMirror 5 and Mermaid come from pinned
 * CDN URLs; when CodeMirror is missing the page falls back to the plain <textarea>.
 *
 * The block between the "pure helpers" markers uses no DOM, so it can be unit-checked in a
 * bare JS engine (quickjs) without a browser.
 */
(function () {
  "use strict";

  // ==== pure helpers (begin) ====

  const TOOL_NAMES = ["web_search", "read_file", "llm", "send_email", "delete_file", "sanitize", "confirm"];

  // The 10 pipeline stages. `phase` is the diagnostic phase that fails the stage,
  // `artifacts` the compile-result keys the stage produces, `tab` the tab it opens.
  const STAGES = [
    { id: "lexer", label: "Lexer", phase: "lexer", artifacts: ["tokens"], tab: "tokens" },
    { id: "parser", label: "Parser", phase: "parser", artifacts: ["ast"], tab: "ast" },
    { id: "semantic", label: "Semantic", phase: "semantic", artifacts: ["symbols"], tab: "symbols" },
    { id: "ir", label: "IR+CFG", phase: "ir", artifacts: ["ir", "cfg"], tab: "ir" },
    { id: "taint", label: "Taint", phase: "taint", artifacts: ["taint"], tab: "taint" },
    { id: "approval", label: "Approval", phase: "approval", artifacts: ["approval"], tab: "approval" },
    { id: "optimizer", label: "Optimizer", phase: "optimizer", artifacts: ["optimized_ir"], tab: "optimized" },
    { id: "scheduler", label: "Scheduler", phase: "scheduler", artifacts: ["schedule"], tab: "rounds" },
    { id: "codegen", label: "Codegen", phase: "codegen", artifacts: ["bytecode"], tab: "bytecode" },
    { id: "vm", label: "VM", phase: "runtime", artifacts: [], tab: "output" },
  ];

  const TABS = [
    { id: "errors", label: "Errors" },
    { id: "tokens", label: "Tokens", artifact: "tokens", stage: "lexer" },
    { id: "ast", label: "AST", artifact: "ast", stage: "parser" },
    { id: "symbols", label: "Symbols", artifact: "symbols", stage: "semantic" },
    { id: "ir", label: "IR", artifact: "ir", stage: "ir" },
    { id: "cfg", label: "CFG", artifact: "cfg", stage: "ir" },
    { id: "taint", label: "Taint", artifact: "taint", stage: "taint" },
    { id: "approval", label: "Approval", artifact: "approval", stage: "approval" },
    { id: "optimized", label: "Optimized IR", artifact: "optimized_ir", stage: "optimizer" },
    { id: "rounds", label: "Rounds", artifact: "schedule", stage: "scheduler" },
    { id: "bytecode", label: "Bytecode", artifact: "bytecode", stage: "codegen" },
    { id: "output", label: "Output", stage: "vm" },
  ];

  const TWO_CHAR_OPS = ["->", "==", "!=", "<=", ">="];

  /** Character range [from, to) (0-based) of the token that starts at 1-based `col`.
   *  Strings span to their closing quote (or the line end when unterminated), words span
   *  [A-Za-z0-9_]*, operators use longest match. Past the line end the range is empty
   *  (E201 points just after the previous token), which the editor shows as a bookmark. */
  function tokenRange(lineText, col) {
    const text = String(lineText == null ? "" : lineText);
    const ch = Math.max(0, (col | 0) - 1);
    if (ch >= text.length) return { from: ch, to: ch };
    const c = text[ch];
    if (c === '"') {
      let j = ch + 1;
      while (j < text.length) {
        if (text[j] === "\\") { j += 2; continue; }
        if (text[j] === '"') { j += 1; break; }
        j += 1;
      }
      return { from: ch, to: Math.min(j, text.length) };
    }
    if (/[A-Za-z0-9_]/.test(c)) {
      let j = ch + 1;
      while (j < text.length && /[A-Za-z0-9_]/.test(text[j])) j += 1;
      return { from: ch, to: j };
    }
    if (TWO_CHAR_OPS.indexOf(text.substr(ch, 2)) >= 0) return { from: ch, to: ch + 2 };
    return { from: ch, to: ch + 1 };
  }

  /** A neutral value of an AgentScript type given as text ("string", "list<int>", ...). */
  function defaultValueFor(type) {
    const t = String(type || "").replace(/\s+/g, "");
    if (t === "int") return 0;
    if (t === "bool") return false;
    if (t.indexOf("list") === 0) return [];
    return "";
  }

  /** Run arguments for `task`: the example's run.args when the example targets this task,
   *  otherwise one neutral value per declared parameter. */
  function defaultArgs(task, exampleRun) {
    if (!task) return {};
    if (exampleRun && exampleRun.task === task.name && exampleRun.args && typeof exampleRun.args === "object") {
      return JSON.parse(JSON.stringify(exampleRun.args));
    }
    const args = {};
    for (const p of task.params || []) args[p.name] = defaultValueFor(p.type);
    return args;
  }

  /** One-line JSON with a space after ':' and ',' so the args box reads naturally. */
  function formatArgs(args) {
    const keys = Object.keys(args || {});
    if (keys.length === 0) return "{}";
    return "{" + keys.map((k) => JSON.stringify(k) + ": " + JSON.stringify(args[k])).join(", ") + "}";
  }

  function isErrorExample(ex) {
    return Boolean(ex.expect || (ex.run && ex.run.expect) || (ex.warnings && ex.warnings.length));
  }

  /** Split the manifest into picker groups, keeping each entry's manifest index. */
  function groupExamples(examples) {
    const valid = [];
    const errors = [];
    (examples || []).forEach((ex, index) => {
      (isErrorExample(ex) ? errors : valid).push({ index, file: ex.file, title: ex.title || ex.file });
    });
    return { valid, errors };
  }

  /** The "what should happen" line shown under the picker. */
  function expectSummary(ex) {
    if (!ex) return "";
    const at = (e) => e.code + " at " + e.line + ":" + e.col;
    const parts = [];
    if (ex.expect) parts.push("Expected: " + at(ex.expect) + " (" + ex.expect.phase + ")");
    for (const w of ex.warnings || []) parts.push("Warns " + at(w));
    if (ex.run && ex.run.expect) parts.push("Run " + ex.run.task + " fails " + at(ex.run.expect));
    if (parts.length === 0) parts.push(ex.run ? "Expected: compiles; run " + ex.run.task + " succeeds" : "Expected: compiles");
    return parts.join(" · ");
  }

  /** Does this compile result match what the manifest says the example should do?
   *  Returns {text, match}: match is true or false, or null when there is nothing to check. */
  function expectationCheck(ex, compileResp) {
    if (!ex) return { text: "", match: null };
    const summary = expectSummary(ex);
    if (!compileResp) return { text: summary, match: null };
    const err = firstError(compileResp.diagnostics);
    let match;
    if (ex.expect) {
      match = Boolean(err && err.code === ex.expect.code && err.line === ex.expect.line && err.col === ex.expect.col);
    } else {
      const codes = (compileResp.diagnostics || []).filter((d) => d.severity === "warning").map((d) => d.code);
      match = !err && (ex.warnings || []).every((w) => codes.indexOf(w.code) >= 0);
    }
    return { text: summary, match };
  }

  function firstError(diags) {
    return (diags || []).find((d) => d && d.severity !== "warning") || null;
  }

  function hasArtifact(phases, key) {
    return Boolean(phases && phases[key] !== null && phases[key] !== undefined);
  }

  /** Index of the stage a compile error belongs to: by diagnostic phase, else (e.g. an
   *  internal E000) the first stage whose artifacts are missing. */
  function failingStageIndex(compileResp) {
    if (!compileResp) return -1;
    const err = firstError(compileResp.diagnostics);
    if (!err) return -1;
    const byPhase = STAGES.findIndex((s) => s.id !== "vm" && s.phase === err.phase);
    if (byPhase >= 0) return byPhase;
    const phases = compileResp.phases || {};
    const missing = STAGES.findIndex((s) => s.artifacts.length && s.artifacts.some((k) => !hasArtifact(phases, k)));
    return missing >= 0 ? missing : STAGES.length - 2;
  }

  /** Status of every stage: "idle" (not run), "pass", "warn", "fail" or "skipped". */
  function stageStatuses(compileResp, runResp) {
    const out = STAGES.map((s) => ({ id: s.id, label: s.label, tab: s.tab, status: "idle", code: null, message: null }));
    if (!compileResp) return out;
    const diags = compileResp.diagnostics || [];
    const phases = compileResp.phases || {};
    const failIdx = failingStageIndex(compileResp);
    const err = firstError(diags);
    for (let i = 0; i < STAGES.length - 1; i += 1) {
      const s = STAGES[i];
      const o = out[i];
      if (failIdx >= 0 && i === failIdx) {
        o.status = "fail";
        o.code = err.code;
        o.message = err.message;
      } else if (failIdx >= 0 && i > failIdx) {
        o.status = "idle";
      } else if (!s.artifacts.some((k) => hasArtifact(phases, k))) {
        o.status = "skipped";
      } else {
        const warn = diags.find((d) => d.severity === "warning" && d.phase === s.phase);
        o.status = warn ? "warn" : "pass";
        if (warn) { o.code = warn.code; o.message = warn.message; }
      }
    }
    const vm = out[STAGES.length - 1];
    if (runResp && failIdx < 0) {
      const rerr = firstError((runResp.diagnostics || []).filter((d) => d.phase === "runtime"));
      if (rerr) {
        vm.status = "fail";
        vm.code = rerr.code;
        vm.message = rerr.message;
      } else if (runResp.ok) {
        vm.status = "pass";
      }
    }
    return out;
  }

  /** The per-task list inside a phase's data, whatever container the phase used. */
  function tasksOf(data) {
    if (!data) return [];
    if (Array.isArray(data)) return data.filter((t) => t && typeof t === "object");
    if (Array.isArray(data.tasks)) return data.tasks.filter((t) => t && typeof t === "object");
    const src = data.tasks && typeof data.tasks === "object" ? data.tasks : data;
    return Object.keys(src)
      .filter((k) => src[k] && typeof src[k] === "object" && !Array.isArray(src[k]))
      .map((k) => Object.assign({ name: k }, src[k]));
  }

  function taskName(t, i) {
    return t.name || t.task || "task " + (i + 1);
  }

  /** Mermaid sources from the cfg artifact: [{name, mermaid}]. */
  function cfgGraphs(data) {
    if (data && typeof data.mermaid === "string") return [{ name: data.name || "cfg", mermaid: data.mermaid }];
    return tasksOf(data)
      .map((t, i) => ({ name: taskName(t, i), mermaid: t.mermaid }))
      .filter((g) => typeof g.mermaid === "string" && g.mermaid.trim() !== "");
  }

  function pushLines(target, list) {
    for (const item of list || []) {
      const n = typeof item === "number" ? item : item && typeof item.line === "number" ? item.line : NaN;
      if (Number.isInteger(n) && n > 0) target.add(n);
    }
  }

  /** Source lines that hold untrusted values: the taint data plus, on E401, the whole path. */
  function collectTaintedLines(taintData, diagnostics) {
    const lines = new Set();
    if (taintData && typeof taintData === "object") {
      if (Array.isArray(taintData.tainted_lines)) pushLines(lines, taintData.tainted_lines);
      if (!Array.isArray(taintData)) {
        for (const t of tasksOf(taintData)) {
          pushLines(lines, t.tainted_lines);
          pushLines(lines, t.untrusted);
        }
      }
    }
    for (const d of diagnostics || []) {
      if (d && d.code === "E401") {
        pushLines(lines, [d]);
        pushLines(lines, d.path);
      }
    }
    return Array.from(lines).sort((a, b) => a - b);
  }

  function formatChange(c) {
    if (typeof c === "string") return c;
    if (!c || typeof c !== "object") return String(c);
    const body = c.text || c.description || c.message || c.detail || JSON.stringify(c);
    const kind = c.kind || c.rule || c.pass;
    const where = c.line ? "line " + c.line + ": " : "";
    return where + (kind && body.indexOf(kind) !== 0 ? kind + ": " : "") + body;
  }

  /** Optimizer changes as [{task, text}] from optimized_ir.data (tasks[*].report.changes). */
  function optimizerChanges(data) {
    const out = [];
    if (!data) return out;
    if (Array.isArray(data.changes)) {
      for (const c of data.changes) out.push({ task: null, text: formatChange(c) });
    }
    tasksOf(data).forEach((t, i) => {
      const changes = (t.report && t.report.changes) || t.changes || [];
      for (const c of changes) out.push({ task: taskName(t, i), text: formatChange(c) });
    });
    return out;
  }

  /** Compact JSON for table cells; strings keep their quotes so types stay visible. */
  function formatValue(v) {
    if (v === undefined) return "";
    try {
      return JSON.stringify(v);
    } catch (e) {
      return String(v);
    }
  }

  function truncate(s, n) {
    const str = String(s);
    return str.length > n ? str.slice(0, n - 1) + "…" : str;
  }

  function countDiagnostics(diags) {
    let errors = 0;
    let warnings = 0;
    for (const d of diags || []) {
      if (d.severity === "warning") warnings += 1;
      else errors += 1;
    }
    return { errors, warnings };
  }

  /** Compile diagnostics plus the run's runtime ones (a run's compile diagnostics repeat). */
  function allDiagnostics(compileResp, runResp) {
    const list = ((compileResp && compileResp.diagnostics) || []).slice();
    for (const d of (runResp && runResp.diagnostics) || []) {
      if (d.phase === "runtime") list.push(d);
    }
    return list;
  }

  function locationText(d) {
    return d.line > 0 ? d.line + ":" + d.col : "no location";
  }

  /** Text form used in tooltips: `E401 [taint] 9:14: message`. */
  function diagText(d) {
    return d.code + " [" + d.phase + "] " + (d.line > 0 ? d.line + ":" + d.col + ": " : "") + d.message;
  }

  /** Budget meter numbers: percentage filled (capped at 100) and a severity level. */
  function budgetMeter(used, budget, failed) {
    const u = Number(used) || 0;
    const b = Number(budget) || 0;
    const pct = b > 0 ? Math.min(100, Math.round((u / b) * 100)) : u > 0 ? 100 : 0;
    const level = failed ? "fail" : b > 0 && u >= b ? "full" : "ok";
    return { used: u, budget: b, pct, level };
  }

  // ==== pure helpers (end) ====

  // ------------------------------------------------------------------ DOM helpers

  const $ = (sel) => document.querySelector(sel);

  /** Tiny element builder. Text goes through textContent, never innerHTML. */
  function h(tag, attrs, ...children) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "text") el.textContent = v;
      else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
      else if (k === "dataset") Object.assign(el.dataset, v);
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const c of children.flat()) {
      if (c === null || c === undefined || c === false) continue;
      el.appendChild(typeof c === "string" || typeof c === "number" ? document.createTextNode(String(c)) : c);
    }
    return el;
  }

  // One stroke family for every pictogram: 24-unit grid, 2.2 stroke, square caps.
  const ICONS = {
    check: "M5 12.5l4.5 4.5L19 7.5",
    cross: "M6 6l12 12M18 6L6 18",
    warn: "M12 4L2.8 20h18.4zM12 10v4.5M12 17.2v.1",
    dash: "M6 12h12",
    arrow: "M4 12h13M12 5l7 7-7 7",
    stop: "M8.2 3h7.6L21 8.2v7.6L15.8 21H8.2L3 15.8V8.2zM8 12h8",
    play: "M7 4.5v15l12-7.5z",
    pause: "M8 5v14M16 5v14",
    busy: "M12 3a9 9 0 1 0 9 9",
  };

  function icon(name, cls) {
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("class", "icon icon-" + name + (cls ? " " + cls : ""));
    const path = document.createElementNS(ns, "path");
    path.setAttribute("d", ICONS[name] || ICONS.dash);
    svg.appendChild(path);
    return svg;
  }

  function clear(el) {
    while (el.firstChild) el.removeChild(el.firstChild);
  }

  function storageGet(key) {
    try {
      return window.localStorage.getItem(key);
    } catch (e) {
      return null;
    }
  }

  function storageSet(key, value) {
    try {
      window.localStorage.setItem(key, value);
    } catch (e) {
      /* private mode or blocked storage: the preference just isn't remembered */
    }
  }

  // ------------------------------------------------------------------ state

  const state = {
    examples: [],
    exampleIndex: -1,
    exampleRun: null,
    compile: null,
    compiledSource: null,
    run: null,
    runSource: null,
    compiling: null, // the in-flight compile promise
    running: false,
    activeTab: "errors",
    argsTask: null,
    forceArgs: false,
    confirm: true,
    cfgShowText: false,
    selectedDiag: -1,
  };

  let editor = null;

  // ------------------------------------------------------------------ toasts and status

  function toast(message, kind) {
    const host = $("#toasts");
    const el = h("div", { class: "toast toast-" + (kind || "error"), role: "alert" },
      h("span", { class: "toast-msg", text: message }),
      h("button", { type: "button", class: "toast-close", "aria-label": "Dismiss", onclick: () => el.remove() }, icon("cross")));
    host.appendChild(el);
    window.setTimeout(() => el.classList.add("is-leaving"), 6500);
    window.setTimeout(() => el.remove(), 7000);
  }

  const CHANNEL_ICON = { ok: "check", warning: "warn", error: "stop", busy: "busy" };

  /** The channel sign under the gates: green when cleared, red when stopped. */
  function setStatus(text, kind) {
    const el = $("#status");
    el.textContent = text;
    el.className = "status" + (kind ? " status-" + kind : "");
    const channel = $("#channel");
    channel.dataset.kind = kind || "busy";
    const host = channel.querySelector(".channel-icon");
    clear(host);
    host.appendChild(icon(CHANNEL_ICON[kind] || "busy"));
  }

  /** "Expected: ..." on the right of the channel sign, marked when the compile agrees. */
  function renderExpectation() {
    const el = $("#channel-expect");
    clear(el);
    const ex = state.examples[state.exampleIndex];
    const pristine = Boolean(ex && editor && state.compiledSource === ex.source && editor.getValue() === ex.source);
    const check = expectationCheck(ex, pristine ? state.compile : null);
    if (!check.text) return;
    el.appendChild(h("span", { class: "expect-text", text: check.text }));
    if (check.match !== null) {
      el.appendChild(h("span", { class: "expect-verdict " + (check.match ? "is-match" : "is-miss") },
        icon(check.match ? "check" : "cross"), check.match ? "as expected" : "differs from expected"));
    } else if (ex && state.compiledSource !== null && !pristine) {
      el.appendChild(h("span", { class: "expect-verdict is-edited", text: "source edited" }));
    }
  }

  // ------------------------------------------------------------------ editor adapters

  function defineMode(CM) {
    CM.defineSimpleMode("agentscript", {
      start: [
        { regex: /\/\/.*/, token: "comment" },
        { regex: /"(?:[^\\"]|\\.)*"?/, token: "string" },
        { regex: /(agent|task|let)(\s+)([A-Za-z_]\w*)/, token: ["keyword", null, "def"] },
        { regex: /(?:agent|permit|budget|calls|task|let|if|else|repeat|return)\b/, token: "keyword" },
        { regex: /(?:true|false)\b/, token: "atom" },
        { regex: /(?:string|int|bool|list)\b/, token: "type" },
        { regex: new RegExp("(?:" + TOOL_NAMES.join("|") + ")\\b"), token: "tool" },
        { regex: /[0-9]+/, token: "number" },
        { regex: /->|==|!=|<=|>=|[-+*=<>]/, token: "operator" },
        { regex: /\{/, token: "bracket", indent: true },
        { regex: /\}/, token: "bracket", dedent: true },
        { regex: /[()[\]]/, token: "bracket" },
        { regex: /[,;:]/, token: "punctuation" },
        { regex: /[A-Za-z_]\w*/, token: "variable" },
        // Anything else is an E102 illegal character: show it in the error colour.
        { regex: /\S/, token: "illegal" },
      ],
      meta: { lineComment: "//", electricInput: /^\s*\}$/ },
    });
  }

  function createCodeMirrorEditor(textarea, CM) {
    defineMode(CM);
    const cm = CM.fromTextArea(textarea, {
      mode: "agentscript",
      lineNumbers: true,
      styleActiveLine: true,
      indentUnit: 2,
      tabSize: 2,
      indentWithTabs: false,
      smartIndent: true,
      viewportMargin: 50,
      gutters: ["CodeMirror-linenumbers", "diag-gutter"],
      extraKeys: {
        Tab: (c) => (c.somethingSelected() ? c.indentSelection("add") : c.replaceSelection("  ", "end")),
        "Shift-Tab": (c) => c.indentSelection("subtract"),
        "Ctrl-/": "toggleComment",
        "Cmd-/": "toggleComment",
      },
    });
    let marks = [];
    let gutterLines = [];
    let taintLines = [];
    let pathLine = null;

    function clearDiagnostics() {
      marks.forEach((m) => m.clear());
      marks = [];
      gutterLines.forEach((l) => cm.setGutterMarker(l, "diag-gutter", null));
      gutterLines = [];
    }

    function inDoc(line) {
      return line >= 1 && line <= cm.lineCount();
    }

    return {
      kind: "codemirror",
      getValue: () => cm.getValue(),
      setValue(v) {
        cm.setValue(v);
        cm.clearHistory();
        cm.setCursor({ line: 0, ch: 0 });
      },
      onChange: (fn) => cm.on("changes", fn),
      focus: () => cm.focus(),
      refresh: () => cm.refresh(),
      setDiagnostics(diags, onMarkerClick) {
        cm.operation(() => {
          clearDiagnostics();
          const perLine = new Map();
          diags.forEach((d, i) => {
            if (!inDoc(d.line)) return;
            const sev = d.severity === "warning" ? "warning" : "error";
            const lineIdx = d.line - 1;
            const r = tokenRange(cm.getLine(lineIdx), d.col);
            const title = diagText(d);
            if (r.to > r.from) {
              marks.push(cm.markText({ line: lineIdx, ch: r.from }, { line: lineIdx, ch: r.to },
                { className: "sq sq-" + sev, attributes: { title } }));
            } else {
              const widget = h("span", { class: "sq-eol sq-" + sev, title, text: "  " });
              marks.push(cm.setBookmark({ line: lineIdx, ch: r.from }, { widget, insertLeft: true }));
            }
            const entry = perLine.get(lineIdx) || { sev: "warning", titles: [], index: i };
            if (sev === "error" && entry.sev !== "error") { entry.sev = "error"; entry.index = i; }
            entry.titles.push(title);
            perLine.set(lineIdx, entry);
          });
          for (const [lineIdx, entry] of perLine) {
            const marker = h("div", {
              class: "gm gm-" + entry.sev,
              title: entry.titles.join("\n"),
              onmousedown: (e) => { e.preventDefault(); onMarkerClick(entry.index); },
            });
            cm.setGutterMarker(lineIdx, "diag-gutter", marker);
            gutterLines.push(lineIdx);
          }
        });
      },
      setTaintLines(lines) {
        cm.operation(() => {
          taintLines.forEach((l) => cm.removeLineClass(l, "background", "cm-tainted"));
          taintLines = [];
          for (const n of lines || []) {
            if (!inDoc(n)) continue;
            cm.addLineClass(n - 1, "background", "cm-tainted");
            taintLines.push(n - 1);
          }
        });
      },
      highlightLine(line) {
        if (pathLine !== null) cm.removeLineClass(pathLine, "background", "cm-path-hl");
        pathLine = null;
        if (line && inDoc(line)) {
          pathLine = line - 1;
          cm.addLineClass(pathLine, "background", "cm-path-hl");
        }
      },
      jumpTo(line, col) {
        if (!inDoc(line)) return;
        const lineIdx = line - 1;
        const r = tokenRange(cm.getLine(lineIdx), col || 1);
        cm.focus();
        cm.setSelection({ line: lineIdx, ch: r.to }, { line: lineIdx, ch: r.from });
        cm.scrollIntoView({ line: lineIdx, ch: r.from }, 120);
        cm.addLineClass(lineIdx, "background", "cm-flash");
        window.setTimeout(() => cm.removeLineClass(lineIdx, "background", "cm-flash"), 900);
      },
    };
  }

  function createTextareaEditor(textarea) {
    textarea.classList.add("is-active");
    return {
      kind: "textarea",
      getValue: () => textarea.value,
      setValue(v) {
        textarea.value = v;
      },
      onChange: (fn) => textarea.addEventListener("input", fn),
      focus: () => textarea.focus(),
      refresh() {},
      setDiagnostics() {},
      setTaintLines() {},
      highlightLine() {},
      jumpTo(line, col) {
        const lines = textarea.value.split("\n");
        if (line < 1 || line > lines.length) return;
        let offset = 0;
        for (let i = 0; i < line - 1; i += 1) offset += lines[i].length + 1;
        const r = tokenRange(lines[line - 1], col || 1);
        textarea.focus();
        textarea.setSelectionRange(offset + r.from, offset + Math.max(r.to, r.from));
      },
    };
  }

  function createEditor() {
    const textarea = $("#source");
    const CM = window.CodeMirror;
    if (CM && typeof CM.fromTextArea === "function" && typeof CM.defineSimpleMode === "function") {
      try {
        return createCodeMirrorEditor(textarea, CM);
      } catch (e) {
        console.error(e);
      }
    }
    toast("CodeMirror did not load: using a plain text editor (no highlighting or squiggles).", "warning");
    return createTextareaEditor(textarea);
  }

  // ------------------------------------------------------------------ API

  async function api(path, body) {
    const ctrl = typeof AbortController === "function" ? new AbortController() : null;
    const timer = ctrl ? window.setTimeout(() => ctrl.abort(), 90000) : null;
    try {
      const res = await fetch(path, {
        method: body === undefined ? "GET" : "POST",
        headers: body === undefined ? {} : { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: ctrl ? ctrl.signal : undefined,
      });
      let payload = null;
      try {
        payload = await res.json();
      } catch (e) {
        payload = null;
      }
      if (!res.ok) {
        const detail = payload && payload.detail ? ": " + (typeof payload.detail === "string" ? payload.detail : JSON.stringify(payload.detail)) : "";
        throw new Error(path + " failed (HTTP " + res.status + ")" + detail);
      }
      if (payload === null) throw new Error(path + " returned no JSON");
      return payload;
    } catch (e) {
      if (e && e.name === "AbortError") throw new Error(path + " timed out");
      if (e instanceof TypeError) throw new Error("Cannot reach the AgentScript server (" + path + "). Is `python -m agentscript serve` running?");
      throw e;
    } finally {
      if (timer) window.clearTimeout(timer);
    }
  }

  // ------------------------------------------------------------------ pipeline strip

  const STATUS_TEXT = { idle: "not run", pass: "passed", warn: "passed with a warning", fail: "failed", skipped: "skipped" };
  const STATUS_ICON = { idle: "dash", pass: "check", warn: "warn", fail: "cross", skipped: "dash" };

  function renderPipeline() {
    const strip = $("#pipeline-strip");
    clear(strip);
    const statuses = stageStatuses(state.compile, state.run);
    statuses.forEach((s, i) => {
      const title = s.label + ": " + STATUS_TEXT[s.status] + (s.code ? " (" + s.code + (s.message ? ": " + s.message : "") + ")" : "");
      strip.appendChild(h("li", { class: "stage stage-" + s.status },
        h("button", { type: "button", class: "stage-chip", title, "aria-label": title, onclick: () => activateTab(s.tab) },
          h("span", { class: "stage-num", text: String(i + 1) }),
          h("span", { class: "stage-label", text: s.label }),
          s.code ? h("span", { class: "stage-code", text: s.code }) : null,
          h("span", { class: "stage-icon" }, icon(STATUS_ICON[s.status])))));
    });
    return statuses;
  }

  // ------------------------------------------------------------------ tabs

  function buildTabs() {
    const bar = $("#tabbar");
    const panels = $("#panels");
    for (const t of TABS) {
      bar.appendChild(h("button", {
        type: "button", class: "tab", role: "tab", id: "tab-" + t.id, "aria-controls": "panel-" + t.id,
        "aria-selected": "false", tabindex: "-1", dataset: { tab: t.id },
        onclick: () => activateTab(t.id),
      }, h("span", { class: "tab-dot", "aria-hidden": "true" }), h("span", { class: "tab-label", text: t.label }),
      t.id === "errors" ? h("span", { class: "badge", id: "error-badge", hidden: true }) : null));
      panels.appendChild(h("div", { class: "panel", role: "tabpanel", id: "panel-" + t.id, "aria-labelledby": "tab-" + t.id, hidden: true, tabindex: "0" }));
    }
    bar.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft" && e.key !== "Home" && e.key !== "End") return;
      e.preventDefault();
      const i = TABS.findIndex((t) => t.id === state.activeTab);
      let j = i;
      if (e.key === "ArrowRight") j = (i + 1) % TABS.length;
      if (e.key === "ArrowLeft") j = (i - 1 + TABS.length) % TABS.length;
      if (e.key === "Home") j = 0;
      if (e.key === "End") j = TABS.length - 1;
      activateTab(TABS[j].id);
      $("#tab-" + TABS[j].id).focus();
    });
  }

  function activateTab(id) {
    if (!TABS.some((t) => t.id === id)) return;
    state.activeTab = id;
    storageSet("agentscript.tab", id);
    for (const t of TABS) {
      const on = t.id === id;
      const btn = $("#tab-" + t.id);
      btn.classList.toggle("is-active", on);
      btn.setAttribute("aria-selected", on ? "true" : "false");
      btn.setAttribute("tabindex", on ? "0" : "-1");
      $("#panel-" + t.id).hidden = !on;
    }
    const activeBtn = $("#tab-" + id);
    if (activeBtn && activeBtn.scrollIntoView) activeBtn.scrollIntoView({ block: "nearest", inline: "nearest" });
    updateTaintHighlight();
    if (id === "cfg") renderCfgGraphs();
  }

  function updateTabDecorations(statuses) {
    const byStage = new Map(statuses.map((s) => [s.id, s.status]));
    for (const t of TABS) {
      const btn = $("#tab-" + t.id);
      const st = t.stage ? byStage.get(t.stage) : null;
      btn.dataset.status = st || "";
    }
    const counts = countDiagnostics(allDiagnostics(state.compile, state.run));
    const badge = $("#error-badge");
    const total = counts.errors + counts.warnings;
    badge.hidden = total === 0;
    badge.textContent = String(total);
    badge.className = "badge " + (counts.errors ? "badge-error" : "badge-warning");
    $("#tab-errors").dataset.status = state.compile ? (counts.errors ? "fail" : counts.warnings ? "warn" : "pass") : "";
  }

  // ------------------------------------------------------------------ panel building blocks

  function panelHeader(title, meta, ...extra) {
    return h("div", { class: "panel-head" },
      h("div", { class: "panel-titles" }, h("h2", { class: "panel-title", text: title }), meta ? h("p", { class: "panel-meta", text: meta }) : null),
      extra.length ? h("div", { class: "panel-actions" }, ...extra) : null);
  }

  function pre(text, cls) {
    return h("pre", { class: "code-block" + (cls ? " " + cls : "") }, h("code", { text: text || "" }));
  }

  function emptyState(iconName, title, body, action) {
    return h("div", { class: "empty" },
      h("div", { class: "empty-icon" }, icon(iconName)),
      h("p", { class: "empty-title", text: title }),
      body ? h("p", { class: "empty-body", text: body }) : null,
      action || null);
  }

  function stoppedStage() {
    const statuses = stageStatuses(state.compile, state.run);
    return statuses.find((s) => s.status === "fail") || null;
  }

  /** The panel body for a phase that has no artifact, or null when it has one. */
  function missingArtifactView(tab) {
    if (!state.compile) {
      return emptyState("play", "Nothing compiled yet", "Press Compile (" + modKey() + "+Enter) to fill this tab.");
    }
    const art = state.compile.phases ? state.compile.phases[tab.artifact] : null;
    if (art) return null;
    const statuses = stageStatuses(state.compile, state.run);
    const mine = statuses.find((s) => s.id === tab.stage);
    if (mine && mine.status === "fail") {
      const d = firstError(state.compile.diagnostics);
      return h("div", null,
        h("p", { class: "notice notice-error", text: "This phase found the error that stopped compilation." }),
        diagnosticCard(d, allDiagnostics(state.compile, state.run).indexOf(d)));
    }
    if (mine && mine.status === "skipped") {
      return emptyState("dash", "This phase did not run", "The compiler produced no artifact for it.");
    }
    const stop = stoppedStage();
    const where = stop ? stop.label + (stop.code ? " (" + stop.code + ")" : "") : "an earlier phase";
    return emptyState("pause", "Not reached: compilation stopped at " + where, "Fix the error shown in the Errors tab, then compile again.",
      h("button", { type: "button", class: "btn btn-ghost", text: "Show errors", onclick: () => activateTab("errors") }));
  }

  function diagnosticCard(d, index) {
    if (!d) return null;
    const sev = d.severity === "warning" ? "warning" : "error";
    const located = d.line > 0;
    const steps = Array.isArray(d.path) ? d.path : [];
    const card = h("article", {
      class: "diag diag-" + sev + (index === state.selectedDiag ? " is-selected" : "") + (located ? " is-located" : ""),
      dataset: { index: String(index) },
    },
    h("button", {
      type: "button", class: "diag-main", disabled: !located,
      title: located ? "Jump to " + d.line + ":" + d.col : "This diagnostic has no source location",
      onclick: () => { if (located) editor.jumpTo(d.line, d.col); },
    },
    h("span", { class: "diag-row" },
      h("span", { class: "pill pill-" + sev, text: sev }),
      h("span", { class: "diag-code", text: d.code }),
      h("span", { class: "diag-phase", text: d.phase }),
      h("span", { class: "diag-loc", text: locationText(d) })),
    h("span", { class: "diag-msg", text: d.message })),
    steps.length ? h("div", { class: "diag-path" },
      h("p", { class: "path-title", text: "Path (" + steps.length + " step" + (steps.length === 1 ? "" : "s") + ")" }),
      h("ol", { class: "path-steps" }, steps.map((s, i) => h("li", null,
        h("button", {
          type: "button", class: "path-step" + (i === steps.length - 1 ? " is-last" : ""),
          title: s.line > 0 ? "Jump to " + s.line + ":" + s.col : "",
          onmouseenter: () => editor.highlightLine(s.line),
          onmouseleave: () => editor.highlightLine(null),
          onfocus: () => editor.highlightLine(s.line),
          onblur: () => editor.highlightLine(null),
          onclick: () => { if (s.line > 0) editor.jumpTo(s.line, s.col); },
        },
        h("span", { class: "step-num", text: String(i + 1) }),
        h("span", { class: "step-loc", text: s.line > 0 ? s.line + ":" + s.col : "–" }),
        h("span", { class: "step-note", text: s.note || "" })))))) : null);
    return card;
  }

  function statCard(label, before, after, unit) {
    const has = typeof before === "number" && typeof after === "number";
    const delta = has ? after - before : 0;
    return h("div", { class: "stat" },
      h("p", { class: "stat-label", text: label }),
      h("p", { class: "stat-value" },
        h("span", { class: "stat-before", text: has ? String(before) : "–" }),
        h("span", { class: "stat-arrow", "aria-hidden": "true", text: "→" }),
        h("span", { class: "stat-after", text: has ? String(after) : "–" })),
      h("p", { class: "stat-delta " + (delta < 0 ? "is-better" : delta > 0 ? "is-worse" : "is-same"),
        text: has ? (delta === 0 ? "unchanged" : (delta < 0 ? "−" + -delta : "+" + delta) + " " + unit) : "not available" }));
  }

  function modKey() {
    return /Mac|iPhone|iPad/.test(navigator.platform || "") ? "⌘" : "Ctrl";
  }

  // ------------------------------------------------------------------ panel renderers

  function renderErrors(panel) {
    const diags = allDiagnostics(state.compile, state.run);
    if (!state.compile && !state.run) {
      panel.appendChild(emptyState("play", "Nothing compiled yet", "Pick an example or write a program, then press Compile."));
      return;
    }
    const counts = countDiagnostics(diags);
    panel.appendChild(panelHeader("Errors and warnings",
      counts.errors + " error" + (counts.errors === 1 ? "" : "s") + ", " + counts.warnings + " warning" + (counts.warnings === 1 ? "" : "s") +
      (diags.length ? " · click one to jump to it in the editor" : "")));
    if (diags.length === 0) {
      panel.appendChild(emptyState("check", "No errors or warnings", state.run ? "The program compiled and the run finished cleanly." : "Every compile-time check passed."));
      return;
    }
    panel.appendChild(h("div", { class: "diag-list" }, diags.map((d, i) => diagnosticCard(d, i))));
  }

  function renderArtifactText(panel, tab, title, meta) {
    const art = state.compile.phases[tab.artifact];
    panel.appendChild(panelHeader(title, meta));
    panel.appendChild(pre(art.text));
  }

  function renderTokens(panel, tab) {
    const art = state.compile.phases.tokens;
    const data = Array.isArray(art.data) ? art.data : null;
    panel.appendChild(panelHeader("Tokens", data ? data.length + " tokens · click a row to find it in the source" : null));
    if (!data) {
      panel.appendChild(pre(art.text));
      return;
    }
    const rows = data.map((t, i) => h("tr", {
      class: t.line > 0 ? "is-clickable" : "",
      onclick: () => { if (t.line > 0) editor.jumpTo(t.line, t.col); },
    },
    h("td", { class: "num", text: String(i + 1) }),
    h("td", { class: "mono", text: t.line + ":" + t.col }),
    h("td", null, h("span", { class: "kind kind-" + kindClass(t.kind, t.text), text: t.kind })),
    h("td", { class: "mono", text: t.text === "" ? "" : t.text })));
    panel.appendChild(h("div", { class: "table-wrap" },
      h("table", { class: "table" },
        h("thead", null, h("tr", null, h("th", { text: "#" }), h("th", { text: "Line:col" }), h("th", { text: "Kind" }), h("th", { text: "Text" }))),
        h("tbody", null, rows))));
  }

  /** CSS class for a token kind; the lexer names keywords after their word (LET, STRING_T). */
  function kindClass(kind, text) {
    const k = String(kind || "");
    if (k === "IDENT") return "ident";
    if (k.indexOf("KW_") === 0 || /^[a-z]+$/.test(String(text || ""))) return "keyword";
    if (k === "INT" || k === "STRING") return "literal";
    if (k === "EOF") return "eof";
    return "punct";
  }

  function renderCfg(panel) {
    const art = state.compile.phases.cfg;
    const graphs = cfgGraphs(art.data);
    const canDraw = Boolean(window.mermaid) && graphs.length > 0;
    const showText = state.cfgShowText || !canDraw;
    const toggle = h("div", { class: "segmented segmented-small", role: "radiogroup", "aria-label": "CFG view" },
      h("button", { type: "button", class: "seg-btn" + (!showText ? " is-on" : ""), role: "radio", "aria-checked": String(!showText), disabled: !canDraw,
        text: "Graph", onclick: () => { state.cfgShowText = false; renderPanel("cfg"); renderCfgGraphs(); } }),
      h("button", { type: "button", class: "seg-btn" + (showText ? " is-on" : ""), role: "radio", "aria-checked": String(showText),
        text: "Text", onclick: () => { state.cfgShowText = true; renderPanel("cfg"); } }));
    let meta = graphs.length + " task" + (graphs.length === 1 ? "" : "s") + " · basic blocks and edges";
    if (!window.mermaid) meta = "Mermaid did not load: showing the text form";
    panel.appendChild(panelHeader("Control-flow graph", meta, toggle));
    if (showText) {
      panel.appendChild(pre(art.text));
      return;
    }
    for (const g of graphs) {
      panel.appendChild(h("figure", { class: "cfg-figure" },
        h("figcaption", { class: "cfg-caption", text: "task " + g.name }),
        h("div", { class: "cfg-graph", dataset: { mermaid: g.mermaid } }, h("p", { class: "muted", text: "Drawing..." }))));
    }
  }

  let mermaidReady = false;
  let mermaidSeq = 0;
  const mermaidCache = new Map();

  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function initMermaid() {
    if (!window.mermaid || mermaidReady) return;
    try {
      window.mermaid.initialize({
        startOnLoad: false,
        securityLevel: "strict",
        theme: "base",
        fontFamily: cssVar("--font-mono") || "monospace",
        themeVariables: {
          background: cssVar("--panel"),
          primaryColor: cssVar("--panel-2"),
          primaryTextColor: cssVar("--ink"),
          primaryBorderColor: cssVar("--ink"),
          lineColor: cssVar("--ink-2"),
          secondaryColor: cssVar("--blue-wash"),
          tertiaryColor: cssVar("--panel"),
          edgeLabelBackground: cssVar("--panel"),
          fontSize: "14px",
        },
        flowchart: { curve: "basis", htmlLabels: false, useMaxWidth: false },
      });
      mermaidReady = true;
    } catch (e) {
      console.error(e);
    }
  }

  async function renderCfgGraphs() {
    if (state.activeTab !== "cfg" || !window.mermaid) return;
    initMermaid();
    const nodes = Array.from(document.querySelectorAll("#panel-cfg .cfg-graph"));
    for (const node of nodes) {
      const code = node.dataset.mermaid;
      if (node.dataset.rendered === code) continue;
      node.dataset.rendered = code;
      try {
        let svg = mermaidCache.get(code);
        if (!svg) {
          mermaidSeq += 1;
          const result = await window.mermaid.render("cfg-svg-" + mermaidSeq, code);
          svg = typeof result === "string" ? result : result.svg;
          mermaidCache.set(code, svg);
        }
        if (!node.isConnected) return; // a newer compile replaced the panel
        node.innerHTML = svg; // mermaid output (securityLevel "strict") from our own compiler
      } catch (e) {
        // Mermaid 10 can leave its scratch element behind after a parse error.
        ["cfg-svg-" + mermaidSeq, "dcfg-svg-" + mermaidSeq].forEach((id) => {
          const stray = document.getElementById(id);
          if (stray && !node.contains(stray)) stray.remove();
        });
        clear(node);
        node.appendChild(h("p", { class: "notice notice-warning", text: "Mermaid could not draw this graph: " + (e && e.message ? e.message : e) }));
        node.appendChild(pre(code));
      }
    }
  }

  function renderTaint(panel) {
    const art = state.compile.phases.taint;
    const lines = collectTaintedLines(art && art.data, state.compile.diagnostics);
    panel.appendChild(panelHeader("Taint report", "Untrusted values flow forward from web_search and read_file; only sanitize makes them trusted."));
    panel.appendChild(h("div", { class: "taint-lines" },
      h("span", { class: "field-label", text: lines.length ? "Tainted lines (highlighted in the editor)" : "No untrusted values" }),
      lines.map((n) => h("button", { type: "button", class: "chip chip-taint", text: "line " + n,
        onmouseenter: () => editor.highlightLine(n), onmouseleave: () => editor.highlightLine(null),
        onclick: () => editor.jumpTo(n, 1) }))));
    panel.appendChild(pre(art.text));
  }

  function renderOptimized(panel) {
    const art = state.compile.phases.optimized_ir;
    const stats = state.compile.stats || {};
    const before = stats.before || {};
    const after = stats.after || {};
    const changes = optimizerChanges(art.data);
    panel.appendChild(panelHeader("Optimized IR", "Constant folding, unreachable blocks, dead assignments, duplicate tool calls"));
    panel.appendChild(h("div", { class: "stats" },
      statCard("Instructions", before.instructions, after.instructions, "instructions"),
      statCard("Tool calls", before.calls, after.calls, "calls")));
    panel.appendChild(h("h3", { class: "section-title", text: "Changes (" + changes.length + ")" }));
    if (changes.length) {
      panel.appendChild(h("ul", { class: "changes" }, changes.map((c) => h("li", null,
        c.task ? h("span", { class: "chip", text: c.task }) : null, h("span", { class: "mono", text: c.text })))));
    } else {
      panel.appendChild(h("p", { class: "muted", text: "The optimizer found nothing to change." }));
    }
    panel.appendChild(h("h3", { class: "section-title", text: "Listing" }));
    panel.appendChild(pre(art.text));
  }

  function renderRounds(panel) {
    const art = state.compile.phases.schedule;
    const stats = state.compile.stats || {};
    panel.appendChild(panelHeader("Parallel rounds", "Independent tool calls in one basic block run together as one round"));
    panel.appendChild(h("div", { class: "stats" }, statCard("Rounds", stats.rounds_before, stats.rounds_after, "rounds")));
    panel.appendChild(pre(art.text));
  }

  function renderOutput(panel) {
    const run = state.run;
    if (!run) {
      const msg = state.compile && !state.compile.ok ? "Fix the compile error first, then run a task." : "Choose a task and arguments, then press Run (" + modKey() + "+Shift+Enter).";
      panel.appendChild(emptyState("play", "No run yet", msg));
      return;
    }
    const runtime = (run.diagnostics || []).filter((d) => d.phase === "runtime");
    const compileFailed = !run.ok && runtime.length === 0 && (run.diagnostics || []).length > 0;
    panel.appendChild(panelHeader("Run result", (run.task ? "task " + run.task + " · " : "") + (run.live ? "live tools" : "mock tools") +
      " · confirm " + (run.confirm === false ? "denied" : "approved")));

    const meter = budgetMeter(run.calls_used, run.budget, runtime.some((d) => d.code === "E601"));
    panel.appendChild(h("div", { class: "run-summary" },
      h("div", { class: "result-box " + (run.ok ? "is-ok" : "is-fail") },
        h("p", { class: "stat-label", text: run.ok ? "Returned value" : compileFailed ? "Did not run (compile error)" : "Stopped with a runtime error" }),
        h("pre", { class: "result-value" }, h("code", { text: run.ok ? JSON.stringify(run.value, null, 2) : runtime.length ? runtime[0].code : "–" }))),
      h("div", { class: "meter-box" },
        h("p", { class: "stat-label", text: "Budget" }),
        h("p", { class: "meter-text" }, h("strong", { text: String(meter.used) }), " / " + (run.budget == null ? "?" : run.budget) + " calls"),
        h("div", { class: "meter meter-" + meter.level, role: "meter", "aria-valuemin": "0", "aria-valuemax": String(meter.budget), "aria-valuenow": String(meter.used), "aria-label": "Tool calls used" },
          h("div", { class: "meter-fill", style: "width:" + meter.pct + "%" })),
        typeof run.rounds === "number" && (run.ok || run.rounds > 0) ? h("p", { class: "muted small", text: run.rounds + " round" + (run.rounds === 1 ? "" : "s") }) : null)));

    if (runtime.length) {
      const all = allDiagnostics(state.compile, state.run);
      panel.appendChild(h("div", { class: "diag-list" }, runtime.map((d) => diagnosticCard(d, all.indexOf(d)))));
    } else if (compileFailed) {
      panel.appendChild(h("p", { class: "notice notice-error", text: "The program did not compile; see the Errors tab." }));
    }

    const calls = run.calls || [];
    panel.appendChild(h("h3", { class: "section-title", text: "Call log (" + calls.length + ")" }));
    if (!calls.length) {
      panel.appendChild(h("p", { class: "muted", text: "No tool calls were made." }));
      return;
    }
    const rows = calls.map((c) => {
      const args = (c.args || []).map(formatValue).join(", ");
      const result = formatValue(c.result);
      return h("tr", null,
        h("td", { class: "num", text: String(c.n) }),
        h("td", null, h("span", { class: "tool-name", text: c.tool })),
        h("td", { class: "mono cell-clip", title: args, text: truncate(args, 90) }),
        h("td", { class: "mono cell-clip", title: result, text: truncate(result, 120) }),
        h("td", null, c.line > 0 ? h("button", { type: "button", class: "link", text: String(c.line), onclick: () => editor.jumpTo(c.line, 1) }) : "–"),
        h("td", { class: "num", text: c.round == null ? "–" : String(c.round) }),
        h("td", { class: "note", text: c.note || "" }));
    });
    panel.appendChild(h("div", { class: "table-wrap" },
      h("table", { class: "table table-calls" },
        h("thead", null, h("tr", null, ["#", "Tool", "Args", "Result", "Line", "Round", "Note"].map((t) => h("th", { text: t })))),
        h("tbody", null, rows))));
  }

  const ARTIFACT_TITLES = {
    ast: ["Abstract syntax tree", "Built by the recursive-descent parser"],
    symbols: ["Symbols and scopes", "builtins → agent → task → blocks, plus the worst-path budget per task"],
    ir: ["Three-address code", "Unoptimized IR per task; the safety analyses run on this"],
    approval: ["Approval report", "Dominators, guard blocks and the verdict for each irreversible call"],
    bytecode: ["Bytecode", "Stack-machine instructions run by the VM"],
  };

  function renderPanel(id) {
    const tab = TABS.find((t) => t.id === id);
    const panel = $("#panel-" + id);
    clear(panel);
    if (id === "errors") return renderErrors(panel);
    if (id === "output") return renderOutput(panel);
    const missing = missingArtifactView(tab);
    if (missing) {
      panel.appendChild(panelHeader(tab.label, null));
      panel.appendChild(missing);
      return;
    }
    const mine = stageStatuses(state.compile, state.run).find((s) => s.id === tab.stage);
    if (mine && mine.status === "fail") {
      // The artifact exists but this phase reported the error: show it on top.
      const d = firstError(state.compile.diagnostics);
      panel.appendChild(diagnosticCard(d, allDiagnostics(state.compile, state.run).indexOf(d)));
    }
    if (id === "tokens") return renderTokens(panel, tab);
    if (id === "cfg") return renderCfg(panel);
    if (id === "taint") return renderTaint(panel);
    if (id === "optimized") return renderOptimized(panel);
    if (id === "rounds") return renderRounds(panel);
    const [title, meta] = ARTIFACT_TITLES[id] || [tab.label, null];
    return renderArtifactText(panel, tab, title, meta);
  }

  function renderAll() {
    renderExpectation();
    const statuses = renderPipeline();
    updateTabDecorations(statuses);
    for (const t of TABS) renderPanel(t.id);
    applyDiagnostics();
    updateTaintHighlight();
    if (state.activeTab === "cfg") renderCfgGraphs();
  }

  function applyDiagnostics() {
    const diags = allDiagnostics(state.compile, state.run);
    editor.setDiagnostics(diags, (index) => {
      state.selectedDiag = index;
      activateTab("errors");
      renderPanel("errors");
      const card = document.querySelector('#panel-errors .diag[data-index="' + index + '"]');
      if (card) card.scrollIntoView({ block: "nearest", behavior: "smooth" });
    });
  }

  function updateTaintHighlight() {
    if (!editor) return;
    const c = state.compile;
    if (!c) {
      editor.setTaintLines([]);
      return;
    }
    const failedTaint = (c.diagnostics || []).some((d) => d.code === "E401");
    const show = state.activeTab === "taint" || failedTaint;
    const art = c.phases && c.phases.taint;
    editor.setTaintLines(show ? collectTaintedLines(art && art.data, c.diagnostics) : []);
  }

  // ------------------------------------------------------------------ examples

  function populateExamples() {
    const select = $("#example-select");
    clear(select);
    const groups = groupExamples(state.examples);
    select.appendChild(h("option", { value: "", text: "Choose an example..." }));
    const addGroup = (label, items) => {
      if (!items.length) return;
      select.appendChild(h("optgroup", { label }, items.map((it) => h("option", { value: String(it.index), text: it.title }))));
    };
    addGroup("Valid programs", groups.valid);
    addGroup("Errors", groups.errors);
  }

  function loadExample(index) {
    const ex = state.examples[index];
    if (!ex) return;
    state.exampleIndex = index;
    state.exampleRun = ex.run || null;
    $("#example-select").value = String(index);
    storageSet("agentscript.example", ex.file);
    const desc = $("#example-desc");
    clear(desc);
    desc.appendChild(h("span", { class: "desc-text", text: ex.description || "" }));
    desc.appendChild(h("span", { class: "desc-expect " + (isErrorExample(ex) ? "is-error" : "is-valid"), text: expectSummary(ex) }));
    editor.setValue(ex.source || "");
    state.compile = null;
    state.run = null;
    state.compiledSource = null;
    state.selectedDiag = -1;
    // The example's run request wins over parameter defaults until the user picks a task.
    state.forceArgs = true;
    if (ex.run) {
      setTaskOptions([{ name: ex.run.task, params: [] }], ex.run.task, true);
      $("#args-input").value = formatArgs(ex.run.args || {});
    } else {
      setTaskOptions([], "");
      $("#args-input").value = "{}";
    }
    $("#args-input").classList.remove("is-invalid");
    renderAll();
    compile({ fromExample: true });
  }

  // ------------------------------------------------------------------ run controls

  function setTaskOptions(tasks, selected, provisional) {
    const select = $("#task-select");
    clear(select);
    if (!tasks.length) {
      select.appendChild(h("option", { value: "", text: "No tasks (fix the compile error)" }));
      select.disabled = true;
      return;
    }
    for (const t of tasks) {
      const sig = provisional ? t.name : t.name + "(" + (t.params || []).map((p) => p.name + ": " + p.type).join(", ") + ") -> " + t.return_type;
      select.appendChild(h("option", { value: t.name, text: sig }));
    }
    select.value = selected;
    select.disabled = false;
  }

  function updateTasks() {
    const c = state.compile;
    const tasks = (c && Array.isArray(c.tasks)) ? c.tasks : [];
    if (!tasks.length) {
      // Keep the provisional example task so the run box still reads sensibly.
      if (!state.exampleRun) setTaskOptions([], "");
      return;
    }
    const prev = $("#task-select").value;
    let chosen = tasks.some((t) => t.name === prev) ? prev : tasks[0].name;
    if (state.forceArgs && state.exampleRun && tasks.some((t) => t.name === state.exampleRun.task)) chosen = state.exampleRun.task;
    setTaskOptions(tasks, chosen, false);
    if (state.forceArgs || chosen !== state.argsTask) {
      const task = tasks.find((t) => t.name === chosen);
      $("#args-input").value = formatArgs(defaultArgs(task, state.exampleRun));
      $("#args-input").classList.remove("is-invalid");
      state.argsTask = chosen;
      state.forceArgs = false;
    }
  }

  function onTaskChange() {
    const tasks = (state.compile && state.compile.tasks) || [];
    const task = tasks.find((t) => t.name === $("#task-select").value);
    if (!task) return;
    $("#args-input").value = formatArgs(defaultArgs(task, state.exampleRun));
    $("#args-input").classList.remove("is-invalid");
    state.argsTask = task.name;
  }

  function setConfirm(value) {
    state.confirm = value;
    document.querySelectorAll("[data-confirm]").forEach((b) => {
      const on = (b.dataset.confirm === "true") === value;
      b.classList.toggle("is-on", on);
      b.setAttribute("aria-checked", on ? "true" : "false");
    });
  }

  function setBusy(btn, busy) {
    btn.classList.toggle("is-busy", busy);
    btn.disabled = busy;
  }

  function markDirty() {
    const dirty = state.compiledSource !== null && editor.getValue() !== state.compiledSource;
    $("#edit-hint").hidden = !dirty;
    $("#pipeline-strip").classList.toggle("is-stale", dirty);
    $("#channel").classList.toggle("is-stale", dirty);
    renderExpectation();
  }

  // ------------------------------------------------------------------ compile and run

  function compile(opts) {
    if (state.compiling) return state.compiling;
    const options = opts || {};
    const source = editor.getValue();
    const btn = $("#compile-btn");
    setBusy(btn, true);
    setStatus("Compiling...", "busy");
    const t0 = performance.now();
    state.compiling = (async () => {
      try {
        const resp = await api("/compile", { source });
        state.compile = resp;
        state.compiledSource = source;
        if (state.runSource !== source) state.run = null;
        state.selectedDiag = -1;
        updateTasks();
        renderAll();
        markDirty();
        const ms = Math.round(performance.now() - t0);
        const err = firstError(resp.diagnostics);
        if (err) {
          setStatus(err.code + " " + err.phase + (err.line > 0 ? " at " + err.line + ":" + err.col : "") + " · " + ms + " ms", "error");
          activateTab("errors");
        } else {
          const w = resp.warnings_count || countDiagnostics(resp.diagnostics).warnings;
          setStatus("Compiled OK" + (w ? " with " + w + " warning" + (w === 1 ? "" : "s") : "") + " · " + ms + " ms", w ? "warning" : "ok");
          if (options.fromExample && w) activateTab("errors");
        }
        return true;
      } catch (e) {
        setStatus("Compile failed: network", "error");
        toast(e.message || String(e));
        return false;
      } finally {
        setBusy(btn, false);
        state.compiling = null;
      }
    })();
    return state.compiling;
  }

  async function run() {
    if (state.running) return;
    const source = editor.getValue();
    if (state.compiling) await state.compiling;
    if (!state.compile || state.compiledSource !== source) {
      const ok = await compile();
      if (!ok) return;
    }
    if (!state.compile.ok) {
      toast("The program has a compile error; fix it before running.", "warning");
      activateTab("errors");
      return;
    }
    const task = $("#task-select").value;
    if (!task) {
      toast("No task to run.", "warning");
      return;
    }
    let args;
    const argsBox = $("#args-input");
    try {
      args = JSON.parse(argsBox.value.trim() || "{}");
      if (!args || typeof args !== "object" || Array.isArray(args)) throw new Error("arguments must be a JSON object like {\"topic\": \"AI\"}");
      argsBox.classList.remove("is-invalid");
    } catch (e) {
      argsBox.classList.add("is-invalid");
      toast("Arguments are not valid JSON: " + e.message, "warning");
      argsBox.focus();
      return;
    }
    const live = $("#live-toggle").checked;
    const btn = $("#run-btn");
    state.running = true;
    setBusy(btn, true);
    setStatus("Running " + task + "...", "busy");
    const t0 = performance.now();
    try {
      const resp = await api("/run", { source, task, args, live, confirm: state.confirm });
      state.run = Object.assign({ task, live, confirm: state.confirm }, resp);
      state.runSource = source;
      renderAll();
      activateTab("output");
      const ms = Math.round(performance.now() - t0);
      const err = firstError(resp.diagnostics);
      const n = (resp.calls || []).length;
      if (resp.ok) setStatus("Ran " + task + " · " + n + " call" + (n === 1 ? "" : "s") + " · " + ms + " ms", "ok");
      else setStatus((err ? err.code + " " + err.phase : "Run failed") + " · " + ms + " ms", "error");
    } catch (e) {
      setStatus("Run failed: network", "error");
      toast(e.message || String(e));
    } finally {
      state.running = false;
      setBusy(btn, false);
    }
  }

  // ------------------------------------------------------------------ setup

  const STARTER = [
    "agent Assistant {",
    "  permit web_search, llm, sanitize, send_email, confirm;",
    "  budget calls = 5;",
    "",
    "  task report(topic: string) -> bool {",
    "    let raw = web_search(topic);",
    "    let clean = sanitize(raw[0]);",
    "    let summary = llm(\"Summarize: \" + clean);",
    "    if (confirm(\"Send report?\")) {",
    "      return send_email(\"me@example.com\", summary);",
    "    }",
    "    return false;",
    "  }",
    "}",
    "",
  ].join("\n");

  function applyFontSize(px) {
    const size = Math.max(12, Math.min(28, px));
    document.documentElement.style.setProperty("--code-size", size + "px");
    storageSet("agentscript.fontSize", String(size));
    if (editor) editor.refresh();
    return size;
  }

  function currentFontSize() {
    return parseInt(cssVar("--code-size"), 10) || 16;
  }

  function bindEvents() {
    $("#compile-btn").addEventListener("click", () => compile());
    $("#run-btn").addEventListener("click", () => run());
    $("#example-select").addEventListener("change", (e) => {
      if (e.target.value !== "") loadExample(Number(e.target.value));
    });
    $("#task-select").addEventListener("change", onTaskChange);
    $("#args-input").addEventListener("input", (e) => e.target.classList.remove("is-invalid"));
    document.querySelectorAll("[data-confirm]").forEach((b) => b.addEventListener("click", () => setConfirm(b.dataset.confirm === "true")));
    $("#zoom-in").addEventListener("click", () => applyFontSize(currentFontSize() + 2));
    $("#zoom-out").addEventListener("click", () => applyFontSize(currentFontSize() - 2));
    // Capture phase, so the shortcuts work inside CodeMirror and the args box alike.
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" || !(e.ctrlKey || e.metaKey)) return;
      e.preventDefault();
      e.stopPropagation();
      if (e.shiftKey) run();
      else compile();
    }, true);
    editor.onChange(markDirty);
    const onScheme = () => {
      // Mermaid bakes colours into the SVG: redraw with the new theme.
      mermaidReady = false;
      mermaidCache.clear();
      document.querySelectorAll("#panel-cfg .cfg-graph").forEach((n) => delete n.dataset.rendered);
      renderCfgGraphs();
    };
    $("#theme-btn").addEventListener("click", () => {
      const next = isDark() ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      storageSet("agentscript.theme", next);
      onScheme();
    });
    if (window.matchMedia) {
      const mq = window.matchMedia("(prefers-color-scheme: dark)");
      if (mq.addEventListener) mq.addEventListener("change", onScheme);
    }
  }

  function isDark() {
    const t = document.documentElement.dataset.theme;
    if (t === "dark" || t === "light") return t === "dark";
    return Boolean(window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
  }

  async function start() {
    const mod = modKey();
    document.querySelectorAll("kbd[data-mod]").forEach((k) => { k.textContent = mod; });
    const savedSize = parseInt(storageGet("agentscript.fontSize") || "", 10);
    if (savedSize) applyFontSize(savedSize);
    editor = createEditor();
    buildTabs();
    bindEvents();
    const savedTab = storageGet("agentscript.tab");
    activateTab(TABS.some((t) => t.id === savedTab) ? savedTab : "errors");
    renderAll();
    try {
      state.examples = await api("/examples");
      if (!Array.isArray(state.examples)) throw new Error("/examples did not return a list");
      populateExamples();
      setStatus(state.examples.length + " examples loaded", "ok");
      const savedFile = storageGet("agentscript.example");
      let idx = state.examples.findIndex((x) => x.file === savedFile);
      if (idx < 0) idx = state.examples.findIndex((x) => x.file === "valid_report.as");
      loadExample(idx >= 0 ? idx : 0);
    } catch (e) {
      state.examples = [];
      clear($("#example-select"));
      $("#example-select").appendChild(h("option", { value: "", text: "Examples unavailable" }));
      editor.setValue(STARTER);
      setStatus("Offline: examples not loaded", "error");
      toast(e.message || String(e));
    }
  }

  if (typeof document !== "undefined") {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
    else start();
  }
})();
