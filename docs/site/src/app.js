/* AgentScript docs site: hash router, Markdown rendering, search, TOC, examples, landing. */
(function () {
  "use strict";

  const DATA = JSON.parse(document.getElementById("site-data").textContent);
  const PAGES = DATA.pages;
  const byId = Object.fromEntries(PAGES.map((p) => [p.id, p]));
  const byPath = Object.fromEntries(PAGES.map((p) => [p.path, p]));
  const $ = (sel, root = document) => root.querySelector(sel);
  const main = $("#main");
  const tocEl = $("#toc");
  const HAS_MARKED = typeof window.marked !== "undefined";
  const HAS_MERMAID = typeof window.mermaid !== "undefined";
  const HAS_HLJS = typeof window.hljs !== "undefined";

  // ------------------------------------------------------------- divisions

  const DIVISIONS = {
    "Start here": "d-start",
    "Specification": "d-spec",
    "How it works": "d-how",
    "Presentation": "d-pres",
    "Reference": "d-ref",
  };
  const divClass = (group) => DIVISIONS[group] || "d-ref";
  const firstOf = (group) => PAGES.find((p) => p.group === group);

  const DESCRIPTIONS = {
    "readme": "What each document is and the recommended reading order.",
    "how-it-works--00-overview": "The whole pipeline on one page: what each phase takes, produces and rejects.",
    "how-it-works--01-language": "Agents, tasks, typed variables, if, repeat, tools, permit and budget.",
    "prd": "Grammar, semantics, error taxonomy and milestones; the source of truth.",
    "implementation_plan": "Milestones M1 to M7, data structures, algorithms and the API contract.",
    "how-it-works--02-lexer": "Characters to tokens with line and column; E101, E102.",
    "how-it-works--03-parser": "Recursive descent from tokens to an AST; E201.",
    "how-it-works--04-semantic-analysis": "Scopes, types, permit lists and static call budgets; E301 to E306.",
    "how-it-works--05-ir-and-cfg": "Three-address code split into basic blocks with edges.",
    "how-it-works--06-taint-analysis": "Forward data flow to a fixed point: untrusted data reaching a privileged tool is E401.",
    "how-it-works--07-approval-analysis": "Dominators prove every irreversible call sits behind confirm; E501, E502.",
    "how-it-works--08-optimizer": "Constant folding, dead code and duplicate tool calls, after the safety checks.",
    "how-it-works--09-codegen-and-vm": "IR to stack bytecode, and the VM with its runtime guards; E601 to E604.",
    "how-it-works--10-editor-and-api": "How a Compile click flows through FastAPI, the pipeline and the phase tabs.",
    "how-it-works--11-parallel-scheduling": "Independent tool calls grouped into parallel rounds.",
    "presentation--demo-script": "The live demo, step by step, with the output to expect.",
    "presentation--viva-notes": "Likely questions with prepared answers, one per phase and limitation.",
    "prd-original": "The PRD as first written, kept for reference; superseded by the corrected PRD.",
  };

  // ------------------------------------------------------------- icons (one stroke weight, 24 grid)

  const ICON = {
    arrowR: '<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path d="M5 12h13M12.5 6l6 6-6 6"/></svg>',
    arrowL: '<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path d="M19 12H6M11.5 6l-6 6 6 6"/></svg>',
    chevron: '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M9 5l7 7-7 7"/></svg>',
    stop: '<svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true"><polygon points="8.3,2.5 15.7,2.5 21.5,8.3 21.5,15.7 15.7,21.5 8.3,21.5 2.5,15.7 2.5,8.3"/><path d="M7.5 12h9"/></svg>',
    pass: '<svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true"><circle cx="12" cy="12" r="9.5"/><path d="M7.5 12.5l3 3 6-6.5"/></svg>',
    home: '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M4 11l8-6.5 8 6.5M6.5 9.5V19h11V9.5"/></svg>',
    file: '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M6.5 3.5h7l4 4v13h-11zM13.5 3.5v4h4M9.5 13l-2 2 2 2M14.5 13l2 2-2 2"/></svg>',
    copy: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="8.5" y="8.5" width="11" height="11" rx="1.5"/><path d="M15.5 5.5v-1a1 1 0 0 0-1-1h-9a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1h1"/></svg>',
    check: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
    ext: '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M14 4.5h5.5V10M19.5 4.5L11 13M17 14v5.5H4.5V7H10"/></svg>',
    editor: '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><rect x="3.5" y="4.5" width="17" height="15" rx="1.5"/><path d="M7.5 10l2.5 2-2.5 2M12 15h4.5"/></svg>',
  };

  // ------------------------------------------------------------- utilities

  function esc(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function slugify(text) {
    return String(text)
      .replace(/<[^>]+>/g, "")
      .replace(/&[a-z#0-9]+;/gi, "")
      .toLowerCase()
      .trim()
      .replace(/[^\p{L}\p{N} _-]+/gu, "")
      .replace(/\s/g, "-");
  }

  function normalizePath(path) {
    const out = [];
    for (const part of path.split("/")) {
      if (part === "" || part === ".") continue;
      if (part === "..") out.pop();
      else out.push(part);
    }
    return out.join("/");
  }

  function dirname(path) {
    const i = path.lastIndexOf("/");
    return i < 0 ? "" : path.slice(0, i);
  }

  function route(id, anchor) {
    return "#/doc/" + id + (anchor ? "/" + anchor : "");
  }

  function pageNum(p) {
    const m = p.path.match(/how-it-works\/(\d\d)-/);
    return m ? m[1] : "";
  }

  function navTitle(p) {
    return (p.nav || p.title).replace(/^\d\d\s*[-.:]\s*/, "");
  }

  /** Map a Markdown link (relative to the current doc) to a site route or a GitHub URL. */
  function resolveHref(href, current) {
    if (!href) return { href: "#" };
    if (/^[a-z]+:/i.test(href)) return { href, external: true };
    if (href.startsWith("#")) return { href: route(current.id, href.slice(1)) };
    const [rawPath, anchor] = href.split("#");
    const target = normalizePath(dirname(current.path) + "/" + decodeURIComponent(rawPath));
    const page = byPath[target];
    if (page) return { href: route(page.id, anchor) };
    const kind = /\.[a-z0-9]+$/i.test(target) ? "blob" : "tree";
    return { href: `${DATA.repo}/${kind}/main/${target}${anchor ? "#" + anchor : ""}`, external: true };
  }

  // the editor is served at "/" next to these docs; opened from disk, point at the local server
  const EDITOR_URL = location.protocol === "file:" ? "http://127.0.0.1:8000/" : "/";
  document.querySelectorAll(".editor-link").forEach((a) => { a.href = EDITOR_URL; });
  document.querySelectorAll(".repo-link").forEach((a) => { a.href = DATA.repo; });

  // ------------------------------------------------------------- AgentScript highlighting

  if (HAS_HLJS) {
    hljs.registerLanguage("agentscript", (hl) => ({
      name: "AgentScript",
      keywords: {
        keyword: "agent permit budget calls task let if else repeat return",
        type: "string int bool list",
        literal: "true false",
        sink: "send_email delete_file",
        source: "web_search read_file",
        approval: "confirm",
        sanitizer: "sanitize",
        built_in: "llm",
      },
      contains: [hl.C_LINE_COMMENT_MODE, hl.C_BLOCK_COMMENT_MODE, hl.QUOTE_STRING_MODE, hl.C_NUMBER_MODE],
    }));
  }

  const looksLikeAgentScript = (code) => /^\s*agent\s+\w+\s*\{/m.test(code) || /^\s*(permit|task)\s+\w+/m.test(code) && /;\s*$/m.test(code);

  function highlightCode(code, lang) {
    if (!HAS_HLJS) return esc(code);
    if (lang && hljs.getLanguage(lang)) return hljs.highlight(code, { language: lang, ignoreIllegals: true }).value;
    return esc(code);
  }

  // ------------------------------------------------------------- markdown

  let currentPage = null;
  let slugCounts = {};

  if (HAS_MARKED) {
    marked.use({
      gfm: true,
      renderer: {
        heading(text, level, raw) {
          let slug = slugify(raw);
          if (slugCounts[slug] !== undefined) slug = slug + "-" + ++slugCounts[slug];
          else slugCounts[slug] = 0;
          const a = level >= 2 && level <= 3 ? `<a class="anchor" href="${route(currentPage.id, slug)}" aria-label="Link to this section">#</a>` : "";
          return `<h${level} id="${slug}">${text}${a}</h${level}>\n`;
        },
        code(code, info) {
          let lang = (info || "").trim().split(/\s+/)[0];
          if (lang === "mermaid") return `<div class="mermaid-wrap"><pre class="mermaid" data-src="${esc(code)}">${esc(code)}</pre></div>`;
          if (!lang && looksLikeAgentScript(code)) lang = "agentscript";
          return `<pre><code class="hljs${lang ? " language-" + esc(lang) : ""}">${highlightCode(code, lang)}</code></pre>\n`;
        },
        link(href, title, text) {
          const r = resolveHref(href, currentPage);
          const t = title ? ` title="${esc(title)}"` : "";
          const ext = r.external ? ' target="_blank" rel="noopener"' : "";
          return `<a href="${esc(r.href)}"${t}${ext}>${text}</a>`;
        },
        table(header, body) {
          // key/value tables in the docs have a blank header row: drop it
          if (!header.replace(/<[^>]+>/g, "").trim()) return `<div class="table-wrap"><table class="kv"><tbody>${body}</tbody></table></div>\n`;
          return `<div class="table-wrap"><table><thead>${header}</thead><tbody>${body}</tbody></table></div>\n`;
        },
      },
    });
  }

  function renderMarkdown(page) {
    currentPage = page;
    slugCounts = {};
    if (!HAS_MARKED) {
      return `<div class="fallback-note">Offline: showing the raw Markdown (the Markdown renderer loads from a CDN).</div><div class="raw">${esc(page.md)}</div>`;
    }
    return marked.parse(page.md);
  }

  // ------------------------------------------------------------- theme

  const darkQuery = window.matchMedia ? matchMedia("(prefers-color-scheme: dark)") : null;

  function themeIsDark() {
    const t = document.documentElement.getAttribute("data-theme");
    if (t) return t === "dark";
    return !!(darkQuery && darkQuery.matches);
  }

  function syncThemeButton() {
    const dark = themeIsDark();
    document.documentElement.classList.toggle("is-dark", dark);
    $("#theme-btn").setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
  }

  function setTheme(t) {
    document.documentElement.setAttribute("data-theme", t);
    try { localStorage.setItem("as-docs-theme", t); } catch (e) { /* storage unavailable */ }
    syncThemeButton();
    renderMermaid(main, true);
  }

  // ------------------------------------------------------------- mermaid

  function tok(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function mermaidConfig() {
    const dark = themeIsDark();
    return {
      startOnLoad: false,
      securityLevel: "strict",
      theme: "base",
      fontFamily: '"Atkinson Hyperlegible Next", system-ui, sans-serif',
      themeVariables: {
        darkMode: dark,
        fontFamily: '"Atkinson Hyperlegible Next", system-ui, sans-serif',
        fontSize: "15px",
        background: tok("--panel"),
        primaryColor: tok("--panel-2"),
        primaryTextColor: tok("--ink"),
        primaryBorderColor: tok("--ink-3"),
        secondaryColor: tok("--amber-wash"),
        secondaryTextColor: tok("--ink"),
        secondaryBorderColor: tok("--rule-strong"),
        tertiaryColor: tok("--blue-wash"),
        tertiaryTextColor: tok("--ink"),
        tertiaryBorderColor: tok("--rule-strong"),
        lineColor: tok("--ink-2"),
        textColor: tok("--ink"),
        mainBkg: tok("--panel-2"),
        nodeBorder: tok("--ink-3"),
        clusterBkg: tok("--panel"),
        clusterBorder: tok("--rule-strong"),
        titleColor: tok("--ink"),
        edgeLabelBackground: tok("--panel"),
        noteBkgColor: tok("--amber-wash"),
        noteTextColor: tok("--ink"),
        noteBorderColor: tok("--rule-strong"),
        actorBkg: tok("--panel-2"),
        actorBorder: tok("--ink-3"),
        actorTextColor: tok("--ink"),
        actorLineColor: tok("--ink-3"),
        signalColor: tok("--ink-2"),
        signalTextColor: tok("--ink"),
        labelBoxBkgColor: tok("--panel-2"),
        labelBoxBorderColor: tok("--ink-3"),
        labelTextColor: tok("--ink"),
        loopTextColor: tok("--ink"),
        activationBkgColor: tok("--sign"),
        activationBorderColor: tok("--sign-ink"),
        sequenceNumberColor: tok("--panel"),
      },
    };
  }

  let mermaidRun = Promise.resolve();

  function renderMermaid(root, rerender) {
    const nodes = [...root.querySelectorAll("pre.mermaid")];
    if (!nodes.length || !HAS_MERMAID) return Promise.resolve(); // the diagram source stays visible as text
    mermaidRun = mermaidRun.then(async () => {
      const live = nodes.filter((n) => n.isConnected);
      if (!live.length) return;
      if (rerender) {
        for (const n of live) { n.removeAttribute("data-processed"); n.textContent = n.dataset.src; }
      }
      if (document.fonts && document.fonts.ready) {
        await Promise.race([document.fonts.ready, new Promise((r) => setTimeout(r, 1500))]);
      }
      mermaid.initialize(mermaidConfig());
      try {
        await mermaid.run({ nodes: live.filter((n) => n.isConnected) });
        // keep wide diagrams at their natural size (the frame scrolls) instead of shrinking the text
        for (const n of live) {
          const svg = n.querySelector("svg");
          const w = svg && parseFloat(svg.style.maxWidth);
          if (w) { svg.style.width = w + "px"; svg.style.maxWidth = "none"; }
          const wrap = n.closest(".mermaid-wrap");
          if (wrap && wrap.scrollWidth > wrap.clientWidth + 1 && !wrap.previousElementSibling?.classList.contains("wide-note")) {
            const note = document.createElement("p");
            note.className = "wide-note";
            note.textContent = "Wide diagram: scroll sideways inside the frame to see all of it.";
            wrap.before(note);
          }
        }
      } catch (e) {
        console.info("mermaid", e);
      }
    });
    return mermaidRun;
  }

  // ------------------------------------------------------------- copy buttons

  function addCopyButtons(root) {
    root.querySelectorAll("pre > code").forEach((code) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "copy-btn";
      btn.innerHTML = ICON.copy + "<span>Copy</span>";
      btn.setAttribute("aria-label", "Copy code");
      btn.addEventListener("click", () => {
        const done = () => {
          btn.innerHTML = ICON.check + "<span>Copied</span>";
          btn.classList.add("done");
          setTimeout(() => { btn.innerHTML = ICON.copy + "<span>Copy</span>"; btn.classList.remove("done"); }, 1400);
        };
        if (navigator.clipboard) navigator.clipboard.writeText(code.innerText).then(done, () => {});
      });
      code.parentElement.appendChild(btn);
    });
  }

  // --------------------------------------------------------------- rail

  function groups() {
    const out = [];
    for (const p of PAGES) {
      let g = out.find((x) => x.name === p.group);
      if (!g) out.push((g = { name: p.group, pages: [] }));
      g.pages.push(p);
    }
    return out;
  }

  function lead(p) {
    const n = pageNum(p);
    return n ? `<span class="tile" aria-hidden="true">${n}</span>` : '<span class="plain" aria-hidden="true"></span>';
  }

  function buildSidebar() {
    const parts = [`<nav class="rail-links" aria-label="Site">
        <a class="nav-link" href="${EDITOR_URL}"><span class="ic">${ICON.editor}</span>Editor</a>
        <a class="nav-link" href="${esc(DATA.repo)}" target="_blank" rel="noopener"><span class="ic">${ICON.ext}</span>GitHub</a>
      </nav>
      <div class="rail-top">
        <a class="nav-link" data-route="home" href="#/"><span class="ic">${ICON.home}</span>Home</a>
        <a class="nav-link" data-route="examples" href="#/examples"><span class="ic">${ICON.file}</span>Example programs</a>
      </div>`];
    for (const g of groups()) {
      parts.push(`<section class="division ${divClass(g.name)}"><h2 class="div-head">${esc(g.name)}</h2>`);
      for (const p of g.pages) {
        parts.push(`<a class="nav-link" data-route="${p.id}" href="${route(p.id)}">${lead(p)}<span>${esc(navTitle(p))}</span></a>`);
      }
      parts.push("</section>");
    }
    $("#sidebar").innerHTML = parts.join("");
  }

  function markActive(key) {
    document.querySelectorAll(".nav-link").forEach((a) => {
      const on = a.dataset.route === key;
      a.classList.toggle("active", on);
      if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    document.querySelectorAll(".mast-links a[href='#/examples']").forEach((a) => a.classList.toggle("on", key === "examples"));
    const act = $(".rail .nav-link.active");
    if (act && act.scrollIntoView && !document.body.classList.contains("nav-open")) act.scrollIntoView({ block: "nearest" });
  }

  // ------------------------------------------------------------------- toc

  let tocObserver = null;

  function buildToc() {
    const heads = [...main.querySelectorAll(".doc h2, .doc h3")];
    if (tocObserver) tocObserver.disconnect();
    if (heads.length < 2) { tocEl.innerHTML = ""; return; }
    tocEl.innerHTML = "<h2>On this page</h2>" + heads.map((h) => {
      const label = h.cloneNode(true);
      label.querySelectorAll(".anchor").forEach((a) => a.remove());
      return `<a class="${h.tagName.toLowerCase()}" data-id="${h.id}" href="${route(currentPage.id, h.id)}">${esc(label.textContent)}</a>`;
    }).join("");
    const links = Object.fromEntries([...tocEl.querySelectorAll("a")].map((a) => [a.dataset.id, a]));
    tocObserver = new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (e.isIntersecting) {
          Object.values(links).forEach((a) => a.classList.remove("active"));
          const a = links[e.target.id];
          if (a) {
            a.classList.add("active");
            const box = tocEl.getBoundingClientRect(), r = a.getBoundingClientRect();
            if (r.top < box.top || r.bottom > box.bottom) a.scrollIntoView({ block: "nearest" });
          }
        }
      }
    }, { rootMargin: "-76px 0px -70% 0px" });
    heads.forEach((h) => tocObserver.observe(h));
  }

  // ----------------------------------------------------------------- views

  function enter(html, withToc) {
    document.body.classList.toggle("no-toc", !withToc);
    main.innerHTML = html;
    const first = main.firstElementChild;
    if (first) { first.classList.remove("route-in"); void first.offsetWidth; first.classList.add("route-in"); }
  }

  function gate(p, dir) {
    if (!p) return "";
    const n = pageNum(p);
    const mark = n ? `<span class="tile" aria-hidden="true">${n}</span>` : `<span class="sign-mini" aria-hidden="true"></span>`;
    const label = dir === "prev" ? "Previous" : "Next";
    const text = `<span class="g-text"><span class="g-dir">${label}${p.group ? " · " + esc(p.group) : ""}</span><span class="g-title">${esc(navTitle(p))}</span></span>`;
    const arrow = `<span class="g-arrow">${dir === "prev" ? ICON.arrowL : ICON.arrowR}</span>`;
    return `<a class="gate ${dir} ${divClass(p.group)}" href="${route(p.id)}" rel="${dir}">${dir === "prev" ? arrow + mark + text : text + mark + arrow}</a>`;
  }

  function pager(page) {
    const i = PAGES.indexOf(page);
    return `<nav class="gates" aria-label="Previous and next page">${gate(PAGES[i - 1], "prev") || "<span></span>"}${gate(PAGES[i + 1], "next")}</nav>`;
  }

  /** The division rides in the H1 itself: a numeral tile for a phase page, a hue square otherwise. */
  function markTitle(page) {
    const h1 = main.querySelector(".doc h1");
    if (!h1) return;
    const n = pageNum(page);
    if (n) {
      const first = h1.firstChild;
      if (first && first.nodeType === 3) first.nodeValue = first.nodeValue.replace(/^\s*\d\d\s*[.:-]\s*/, "");
      h1.insertAdjacentHTML("afterbegin", `<span class="tile h1-tile" title="${esc(page.group)}, phase ${n}">${n}</span>`);
    } else {
      h1.insertAdjacentHTML("afterbegin", `<span class="h1-chip" title="${esc(page.group)}" aria-hidden="true"></span>`);
    }
    h1.classList.add("titled");
  }

  async function showDoc(page, anchor) {
    document.title = `${page.title} · AgentScript Docs`;
    enter(`<div class="sheet ${divClass(page.group)}">
      <article class="doc">${renderMarkdown(page)}</article>
      <p class="src-link">Source: <a href="${DATA.repo}/blob/main/${esc(page.path)}" target="_blank" rel="noopener">${esc(page.path)}</a></p>
      ${pager(page)}
    </div>`, true);
    markTitle(page);
    markActive(page.id);
    addCopyButtons(main);
    buildToc();
    const scroll = () => {
      if (anchor) {
        const el = document.getElementById(anchor);
        if (el) { el.scrollIntoView(); return; }
      }
      window.scrollTo(0, 0);
    };
    scroll();
    await renderMermaid(main);
    if (anchor) scroll();
  }

  // ---------------------------------------------------------------- landing

  const STAGES = [
    ["01", "Lexer", "source to tokens", "E101 E102", "how-it-works--02-lexer"],
    ["02", "Parser", "tokens to AST", "E201", "how-it-works--03-parser"],
    ["03", "Semantic", "scopes, types, permit, budget", "E301–E306", "how-it-works--04-semantic-analysis"],
    ["04", "IR + CFG", "three-address code, basic blocks", "", "how-it-works--05-ir-and-cfg"],
    ["05", "Taint", "data-flow fixed point", "E401", "how-it-works--06-taint-analysis", "safety-t"],
    ["06", "Approval", "dominators, guard blocks", "E501 E502", "how-it-works--07-approval-analysis", "safety-a"],
    ["07", "Optimizer", "fold, dead code, duplicate calls", "", "how-it-works--08-optimizer"],
    ["08", "Scheduler", "parallel rounds", "", "how-it-works--11-parallel-scheduling"],
    ["09", "Codegen", "IR to stack bytecode", "", "how-it-works--09-codegen-and-vm"],
    ["10", "VM", "tool registry, runtime guards", "E601–E604", "how-it-works--09-codegen-and-vm"],
  ];

  function listing(source, marks, lang) {
    const lines = source.replace(/\n$/, "").split("\n");
    let html = lines.map(esc);
    if (HAS_HLJS && lang && hljs.getLanguage(lang)) {
      // highlight line by line: AgentScript has no multi-line tokens in these programs
      html = lines.map((ln) => hljs.highlight(ln, { language: lang, ignoreIllegals: true }).value);
    }
    return html.map((h, i) => {
      const m = marks[i + 1];
      return `<span class="ln-row${m ? " mark " + m : ""}"><span class="ln">${i + 1}</span>${h || " "}</span>`;
    }).join("");
  }

  function terminal(run) {
    let out = esc(run.output);
    out = out.replace(/^(E\d{3} \[[a-z]+\] \d+:\d+:)/m, '<span class="hl-bad">$1</span>')
      .replace(/^(compilation failed)$/m, '<span class="hl-bad">$1</span>')
      .replace(/^(compiled OK)$/m, '<span class="hl-ok">$1</span>')
      .replace(/^(value: true)$/m, '<span class="hl-ok">$1</span>');
    const omitted = run.cut ? '<span class="omitted">The phase sections printed before the diagnostics are left out here.</span>' : "";
    return `<div class="term"><div class="term-cmd"><span class="cmd">$ ${esc(run.cmd)}</span><span class="exit">exit ${run.exit}</span></div><pre>${out}${omitted}</pre></div>`;
  }

  function transcript(side, runs) {
    const lines = runs.reduce((n, r) => n + 1 + r.output.split("\n").length, 0);
    return `<div class="transcript">
      <div class="term-clip" id="tr-${side}">${runs.map(terminal).join("")}</div>
      <button type="button" class="term-toggle" aria-expanded="false" aria-controls="tr-${side}">${ICON.chevron}<span class="t-label">Show the full transcript</span><span class="t-count">${lines} lines</span></button>
    </div>`;
  }

  function channel(side) {
    const L = DATA.landing && DATA.landing[side];
    if (!L) return "";
    const red = side === "red";
    const ex = DATA.examples.find((e) => e.file === L.file);
    const marks = {};
    if (red && ex && ex.expect) {
      marks[ex.expect.line] = "hit";
    }
    // green: mark the line that differs from the red program (the added sanitize)
    if (!red && DATA.landing.red) {
      const redLines = new Set(DATA.landing.red.source.split("\n").map((s) => s.trim()));
      L.source.split("\n").forEach((s, i) => { if (/sanitize\(/.test(s) && !redLines.has(s.trim())) marks[i + 1] = "added"; });
    }
    const note = red && ex && ex.expect
      ? `<p class="ch-note"><b>${esc(ex.expect.code)} at ${ex.expect.line}:${ex.expect.col}</b>: the search result flows into <code class="inl">send_email</code> without <code class="inl">sanitize</code>.</p>`
      : `<p class="ch-note"><b>Fixed</b>: <code class="inl">sanitize</code> now sits between the search result and the model, so only trusted data reaches <code class="inl">send_email</code>.</p>`;
    return `<section class="channel ${red ? "ch-red" : "ch-green"}" aria-label="${red ? "Rejected program" : "Program that compiles"}">
      <div class="ch-head">${red ? ICON.stop : ICON.pass}<b>${red ? "Rejected" : "Compiles"}</b>
        <span class="ch-file">examples/${esc(L.file)}</span></div>
      <div class="ch-body">
        <pre class="listing"><code class="hljs language-agentscript">${listing(L.source, marks, "agentscript")}</code></pre>
        ${note}
        ${transcript(side, L.runs)}
      </div>
    </section>`;
  }

  function indexList(g) {
    return `<section class="${divClass(g.name)}"><h3><a class="sign" href="${route(g.pages[0].id)}"><span class="dot" aria-hidden="true"></span>${esc(g.name)}</a></h3><ul>
      ${g.pages.map((p) => {
        const n = pageNum(p);
        return `<li><a href="${route(p.id)}">${n ? `<span class="tile">${n}</span>` : '<span class="i-dot" aria-hidden="true"></span>'}<span class="i-title">${esc(navTitle(p))}</span>${DESCRIPTIONS[p.id] ? `<span class="i-desc">${esc(DESCRIPTIONS[p.id])}</span>` : ""}</a></li>`;
      }).join("")}</ul></section>`;
  }

  function showHome() {
    document.title = "AgentScript Docs";
    const gs = groups();
    const how = gs.find((g) => g.name === "How it works");
    const rest = gs.filter((g) => g !== how);
    enter(`<div class="home">
      <header class="home-head">
        <h1>AgentScript documentation</h1>
        <p>AgentScript is a tiny language for AI-agent programs and a ten-stage compiler that rejects unsafe programs before any tool runs. It proves that <strong>untrusted data</strong> never reaches a privileged tool without <code>sanitize</code>, and that <strong>every irreversible call</strong> sits behind a <code>confirm</code> approval.</p>
        <div class="go">
          <a class="btn primary" href="${route("how-it-works--00-overview")}">Read the overview ${ICON.arrowR}</a>
          <a class="btn" href="${route("how-it-works--01-language")}">The language</a>
          <a class="btn" href="#/examples">Example programs</a>
          <a class="btn" href="${EDITOR_URL}">Open the editor</a>
        </div>
      </header>

      <h2 id="gates" class="first">The ten gates</h2>
      <p class="sub">Every program passes these stages in order, and each prints its own artifact. Taint and approval are the two safety checks.</p>
      <ol class="gates10">${STAGES.map(([n, name, what, codes, id, cls]) =>
        `<li class="${cls || ""}"><a href="${route(id)}"><span class="tile">Stage ${Number(n)}</span><span class="g-name">${name}</span><span class="g-what">${what}</span><span class="g-codes">${codes || "&nbsp;"}</span></a></li>`).join("")}</ol>
      <p class="order-note"><b>Ordering rule.</b> Permission, budget, taint and approval checks run before the optimizer, so a guarantee never depends on what the optimizer removes.</p>

      <h2 id="channels" class="tight">One line apart</h2>
      <div class="channels">${channel("red")}${channel("green")}</div>

      <h2 id="index">All documents</h2>
      <p class="sub">The corrected PRD is the source of truth; the how-it-works series explains each phase with real compiler output.</p>
      <div class="index">
        ${how ? indexList(how) : ""}
        <div style="display:grid;gap:28px;align-content:start">${rest.map(indexList).join("")}</div>
      </div>

      <h2 id="files">Also in the repository</h2>
      <div class="also">
        <a class="btn" href="${DATA.repo}/blob/main/docs/presentation/AgentScript.pptx" target="_blank" rel="noopener">${ICON.ext}Presentation deck (.pptx)</a>
        <a class="btn" href="${DATA.repo}/tree/main/docs/report" target="_blank" rel="noopener">${ICON.ext}IEEE project report</a>
        <a class="btn" href="${DATA.repo}" target="_blank" rel="noopener">${ICON.ext}Source on GitHub</a>
      </div>
    </div>`);
    main.querySelectorAll(".term-toggle").forEach((b) => b.addEventListener("click", () => {
      const open = b.getAttribute("aria-expanded") !== "true";
      b.setAttribute("aria-expanded", String(open));
      b.closest(".transcript").classList.toggle("open", open);
      b.querySelector(".t-label").textContent = open ? "Hide the transcript" : "Show the full transcript";
    }));
    markActive("home");
    tocEl.innerHTML = "";
    window.scrollTo(0, 0);
  }

  // ---------------------------------------------------------------- examples

  let exFilter = "all";

  function exKind(e) {
    if (e.expect) return "error";
    if (e.run && e.run.expect) return "runtime";
    return "valid";
  }

  function badges(e) {
    const b = [];
    if (e.expect) b.push(`<span class="badge err">${esc(e.expect.code)} ${e.expect.line}:${e.expect.col}</span>`);
    else b.push(`<span class="badge ok">compiles</span>`);
    (e.warnings || []).forEach((w) => b.push(`<span class="badge warn">warns ${esc(w.code)} ${w.line}:${w.col}</span>`));
    if (e.run && e.run.expect) b.push(`<span class="badge rt">run ${esc(e.run.expect.code)} ${e.run.expect.line}:${e.run.expect.col}</span>`);
    else if (e.run) b.push(`<span class="badge runs">runs</span>`);
    return b.join("");
  }

  function showExamples(openFile) {
    document.title = "Examples · AgentScript Docs";
    const filters = [["all", "All"], ["valid", "Compiles"], ["error", "Compile errors"], ["runtime", "Runtime errors"]];
    const count = (k) => DATA.examples.filter((e) => k === "all" || exKind(e) === k).length;
    const list = DATA.examples.filter((e) => exFilter === "all" || exKind(e) === exFilter);
    enter(`<div class="sheet wide">
      <article class="doc">
      <h1>Example programs</h1>
      <p>One valid program per feature plus one failing program per error type. These are the files the editor's example picker loads and the tests check. Open a program to see its source; the marked line is where the expected diagnostic points.</p>
      </article>
      <div class="ex-tools"><div class="seg" role="group" aria-label="Filter programs">${filters.map(([k, l]) =>
        `<button type="button" data-f="${k}" class="${k === exFilter ? "on" : ""}" aria-pressed="${k === exFilter}">${l}<span class="count">${count(k)}</span></button>`).join("")}</div></div>
      <div class="ex-list">${list.length ? list.map((e) => {
        const exp = e.expect || (e.run && e.run.expect);
        const warn = (e.warnings || [])[0];
        const marks = {};
        if (warn) marks[warn.line] = "w";
        if (exp) marks[exp.line] = "e";
        const run = e.run ? `<span>Run: <code>python -m agentscript run examples/${esc(e.file)} --task ${esc(e.run.task)} --args '${esc(JSON.stringify(e.run.args))}'</code></span>` : "";
        return `<details class="ex" id="ex-${esc(e.file)}"${openFile === e.file ? " open" : ""}>
          <summary><span class="caret">${ICON.chevron}</span><span class="badges">${badges(e)}</span>
            <span class="ex-main"><span class="ex-title">${esc(e.title)}</span><span class="ex-file">${esc(e.file)}</span><div class="ex-desc">${esc(e.description)}</div></span></summary>
          <div class="ex-detail">
            <pre class="listing"><code class="hljs language-agentscript">${listing(e.source, marks, "agentscript")}</code></pre>
            <div class="meta"><span>Compile: <code>python -m agentscript compile examples/${esc(e.file)}</code></span>${run}</div>
          </div></details>`;
      }).join("") : '<p class="ex-empty">No programs in this group.</p>'}</div>
    </div>`);
    main.querySelectorAll(".seg button").forEach((b) => b.addEventListener("click", () => { exFilter = b.dataset.f; showExamples(); }));
    main.querySelectorAll("details.ex").forEach((d) => d.addEventListener("toggle", () => {
      if (d.open) history.replaceState(null, "", "#/examples/" + d.id.slice(3));
    }));
    // one badge column for every row, as wide as the widest badge stack
    const fitBadges = () => {
      const exl = main.querySelector(".ex-list");
      if (!exl) return;
      exl.style.removeProperty("--badge-w");
      const w = Math.max(0, ...[...exl.querySelectorAll(".badges")].map((b) => b.offsetWidth));
      if (w) exl.style.setProperty("--badge-w", Math.ceil(w) + "px");
    };
    fitBadges();
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(fitBadges);
    markActive("examples");
    tocEl.innerHTML = "";
    const target = openFile && document.getElementById("ex-" + openFile);
    if (target) target.scrollIntoView({ block: "start" });
    else window.scrollTo(0, 0);
  }

  // ---------------------------------------------------------------- router

  function closeNav() {
    document.body.classList.remove("nav-open");
    $("#scrim").hidden = true;
    $("#menu-btn").setAttribute("aria-expanded", "false");
  }

  function router() {
    const hash = location.hash || "#/";
    closeNav();
    const m = hash.match(/^#\/doc\/([^/]+)(?:\/(.+))?$/);
    if (m && byId[m[1]]) return showDoc(byId[m[1]], m[2] && decodeURIComponent(m[2]));
    const ex = hash.match(/^#\/examples(?:\/(.+))?$/);
    if (ex) return showExamples(ex[1] && decodeURIComponent(ex[1]));
    return showHome();
  }

  // ---------------------------------------------------------------- search

  const INDEX = [];
  for (const p of PAGES) {
    const parts = p.md.split(/^(?=#{1,3}\s)/m);
    for (const part of parts) {
      const hm = part.match(/^(#{1,3})\s+(.+)$/m);
      const heading = hm ? hm[2].trim() : p.title;
      const body = part.replace(/^#{1,3}\s+.+$/m, "").replace(/[`*_>|#\[\]()]/g, " ").replace(/\s+/g, " ").trim();
      INDEX.push({ page: p, heading, slug: hm ? slugify(heading) : "", body, lower: (heading + " " + body).toLowerCase() });
    }
  }
  // the renderer de-duplicates repeated heading slugs per page; mirror that here
  const seen = {};
  for (const e of INDEX) {
    if (!e.slug) continue;
    const key = e.page.id + "|" + e.slug;
    if (seen[key] !== undefined) e.slug = e.slug + "-" + ++seen[key];
    else seen[key] = 0;
  }

  const searchBox = $("#search");
  const results = $("#search-results");
  let active = -1;

  function highlight(text, terms) {
    let html = esc(text);
    for (const t of terms) {
      if (!t) continue;
      html = html.replace(new RegExp("(" + esc(t).replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "gi"), "<mark>$1</mark>");
    }
    return html;
  }

  function doSearch() {
    const q = searchBox.value.trim().toLowerCase();
    if (q.length < 2) { results.hidden = true; return; }
    const terms = q.split(/\s+/);
    const hits = [];
    for (const e of INDEX) {
      if (!terms.every((t) => e.lower.includes(t))) continue;
      let score = 0;
      for (const t of terms) {
        if (e.heading.toLowerCase().includes(t)) score += 10;
        if (e.page.title.toLowerCase().includes(t)) score += 4;
        score += Math.min(5, e.lower.split(t).length - 1);
      }
      hits.push({ e, score });
    }
    hits.sort((a, b) => b.score - a.score);
    active = -1;
    if (!hits.length) {
      results.innerHTML = `<div class="sr-empty">No results for “${esc(q)}”. Try a phase name, an error code such as E401, or a tool such as confirm.</div>`;
    } else {
      results.innerHTML = hits.slice(0, 14).map(({ e }) => {
        const i = e.body.toLowerCase().indexOf(terms[0]);
        const start = Math.max(0, i - 50);
        const snip = (start > 0 ? "…" : "") + e.body.slice(start, start + 150) + "…";
        const n = pageNum(e.page);
        return `<a href="${route(e.page.id, e.slug)}"><div class="sr-title">${highlight(e.heading, terms)}</div>
          <div class="sr-page ${divClass(e.page.group)}"><span class="chip" aria-hidden="true"></span>${esc(e.page.group)}${n ? " " + n : ""} · ${esc(navTitle(e.page))}</div><div class="sr-snip">${highlight(snip, terms)}</div></a>`;
      }).join("");
    }
    results.hidden = false;
  }

  searchBox.addEventListener("input", doSearch);
  searchBox.addEventListener("focus", doSearch);
  searchBox.addEventListener("keydown", (ev) => {
    const items = [...results.querySelectorAll("a")];
    if ((ev.key === "ArrowDown" || ev.key === "ArrowUp") && items.length) {
      ev.preventDefault();
      active = (active + (ev.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
      items.forEach((a, i) => a.classList.toggle("active", i === active));
      if (items[active]) items[active].scrollIntoView({ block: "nearest" });
    } else if (ev.key === "Enter" && items.length) {
      location.hash = (items[active] || items[0]).getAttribute("href");
      results.hidden = true;
      searchBox.blur();
    } else if (ev.key === "Escape") {
      results.hidden = true;
      searchBox.blur();
    }
  });
  results.addEventListener("click", () => { results.hidden = true; });
  document.addEventListener("click", (ev) => {
    if (!ev.target.closest(".search-wrap")) results.hidden = true;
  });
  document.addEventListener("keydown", (ev) => {
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
    if (ev.key === "/" && !typing) {
      ev.preventDefault();
      searchBox.focus();
    } else if (ev.key === "Escape" && document.body.classList.contains("nav-open")) {
      closeNav();
      $("#menu-btn").focus();
    }
  });

  // ----------------------------------------------------- theme, menu, progress

  syncThemeButton();
  $("#theme-btn").addEventListener("click", () => setTheme(themeIsDark() ? "light" : "dark"));
  if (darkQuery && darkQuery.addEventListener) {
    darkQuery.addEventListener("change", () => {
      if (!document.documentElement.getAttribute("data-theme")) { syncThemeButton(); renderMermaid(main, true); }
    });
  }

  $("#menu-btn").addEventListener("click", () => {
    const open = !document.body.classList.contains("nav-open");
    document.body.classList.toggle("nav-open", open);
    $("#scrim").hidden = !open;
    $("#menu-btn").setAttribute("aria-expanded", String(open));
    if (open) { const a = $(".rail .nav-link.active") || $(".rail .nav-link"); if (a) a.focus(); }
  });
  $("#scrim").addEventListener("click", closeNav);

  const progress = $("#progress");
  window.addEventListener("scroll", () => {
    const h = document.documentElement.scrollHeight - innerHeight;
    progress.style.width = h > 0 ? (scrollY / h) * 100 + "%" : "0";
  }, { passive: true });

  buildSidebar();
  window.addEventListener("hashchange", router);
  router();
})();
