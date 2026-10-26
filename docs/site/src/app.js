/* AgentScript docs site: hash router, Markdown rendering, search, TOC, examples. */
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

  $("#repo-link").href = DATA.repo;

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
          const a = level >= 2 && level <= 3 ? `<a class="anchor" href="${route(currentPage.id, slug)}" aria-hidden="true">#</a>` : "";
          return `<h${level} id="${slug}">${text}${a}</h${level}>\n`;
        },
        code(code, info) {
          const lang = (info || "").trim().split(/\s+/)[0];
          if (lang === "mermaid") return `<div class="mermaid-wrap"><pre class="mermaid">${esc(code)}</pre></div>`;
          let html = esc(code);
          if (HAS_HLJS && lang && hljs.getLanguage(lang)) {
            html = hljs.highlight(code, { language: lang, ignoreIllegals: true }).value;
          }
          return `<pre><code class="hljs${lang ? " language-" + esc(lang) : ""}">${html}</code></pre>\n`;
        },
        link(href, title, text) {
          const r = resolveHref(href, currentPage);
          const t = title ? ` title="${esc(title)}"` : "";
          const ext = r.external ? ' target="_blank" rel="noopener"' : "";
          return `<a href="${esc(r.href)}"${t}${ext}>${text}</a>`;
        },
        table(header, body) {
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

  function themeIsDark() {
    return document.documentElement.getAttribute("data-theme") !== "light";
  }

  async function renderMermaid(root) {
    const nodes = root.querySelectorAll("pre.mermaid");
    if (!nodes.length) return;
    if (!HAS_MERMAID) return; // the diagram source stays visible as text
    mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: themeIsDark() ? "dark" : "default", fontFamily: "Inter, Arial, sans-serif" });
    try {
      await mermaid.run({ nodes });
    } catch (e) {
      console.warn("mermaid", e);
    }
  }

  function addCopyButtons(root) {
    root.querySelectorAll("pre > code").forEach((code) => {
      const btn = document.createElement("button");
      btn.className = "copy-btn";
      btn.textContent = "Copy";
      btn.addEventListener("click", () => {
        navigator.clipboard.writeText(code.innerText).then(() => {
          btn.textContent = "Copied";
          btn.classList.add("done");
          setTimeout(() => { btn.textContent = "Copy"; btn.classList.remove("done"); }, 1400);
        });
      });
      code.parentElement.appendChild(btn);
    });
  }

  // --------------------------------------------------------------- sidebar

  function buildSidebar() {
    const groups = [];
    for (const p of PAGES) {
      let g = groups.find((x) => x.name === p.group);
      if (!g) groups.push((g = { name: p.group, pages: [] }));
      g.pages.push(p);
    }
    const parts = [`<div class="nav-group"><h4>Overview</h4>
      <a class="nav-link" data-route="home" href="#/"><span class="num">~</span>Home</a>
      <a class="nav-link" data-route="examples" href="#/examples"><span class="num">.as</span>Example programs</a></div>`];
    for (const g of groups) {
      parts.push(`<div class="nav-group"><h4>${esc(g.name)}</h4>`);
      for (const p of g.pages) {
        const m = p.path.match(/how-it-works\/(\d\d)-/);
        const num = m ? m[1] : p.group === "Specification" ? "§" : p.group === "Presentation" ? "▶" : "·";
        const title = (p.nav || p.title).replace(/^\d\d\s*[-.:]\s*/, "");
        parts.push(`<a class="nav-link" data-route="${p.id}" href="${route(p.id)}"><span class="num">${num}</span>${esc(title)}</a>`);
      }
      parts.push("</div>");
    }
    $("#sidebar").innerHTML = parts.join("");
  }

  function markActive(key) {
    document.querySelectorAll(".nav-link").forEach((a) => a.classList.toggle("active", a.dataset.route === key));
  }

  // ------------------------------------------------------------------- toc

  let tocObserver = null;

  function buildToc() {
    const heads = [...main.querySelectorAll(".doc h2, .doc h3")];
    if (tocObserver) tocObserver.disconnect();
    if (heads.length < 2) { tocEl.innerHTML = ""; return; }
    tocEl.innerHTML = "<h4>On this page</h4>" + heads.map((h) => {
      const label = h.cloneNode(true);
      label.querySelectorAll(".anchor").forEach((a) => a.remove());
      return `<a class="${h.tagName.toLowerCase()}" data-id="${h.id}" href="${route(currentPage.id, h.id)}">${esc(label.textContent)}</a>`;
    }).join("");
    const links = Object.fromEntries([...tocEl.querySelectorAll("a")].map((a) => [a.dataset.id, a]));
    tocObserver = new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (e.isIntersecting) {
          Object.values(links).forEach((a) => a.classList.remove("active"));
          if (links[e.target.id]) links[e.target.id].classList.add("active");
        }
      }
    }, { rootMargin: "-70px 0px -70% 0px" });
    heads.forEach((h) => tocObserver.observe(h));
  }

  // ----------------------------------------------------------------- views

  function pager(page) {
    const i = PAGES.indexOf(page);
    const prev = PAGES[i - 1];
    const next = PAGES[i + 1];
    return `<nav class="pager">
      ${prev ? `<a class="prev" href="${route(prev.id)}"><div class="dir">Previous</div><div class="t">${esc(prev.nav || prev.title)}</div></a>` : "<span></span>"}
      ${next ? `<a class="next" href="${route(next.id)}"><div class="dir">Next</div><div class="t">${esc(next.nav || next.title)}</div></a>` : ""}
    </nav>`;
  }

  async function showDoc(page, anchor) {
    document.title = `${page.title} · AgentScript Docs`;
    main.innerHTML = `<article class="doc">
      <div class="crumb"><span class="pill">${esc(page.group)}</span><span>${esc(page.path)}</span></div>
      ${renderMarkdown(page)}
      <div class="edit-link">Source: <a href="${DATA.repo}/blob/main/${esc(page.path)}" target="_blank" rel="noopener">${esc(page.path)}</a></div>
      ${pager(page)}
    </article>`;
    markActive(page.id);
    addCopyButtons(main);
    buildToc();
    await renderMermaid(main);
    if (anchor) {
      const el = document.getElementById(anchor);
      if (el) { el.scrollIntoView(); return; }
    }
    window.scrollTo(0, 0);
  }

  const STAGES = [
    ["01", "Lexer", "source → tokens", "E101 E102", "how-it-works--02-lexer"],
    ["02", "Parser", "tokens → AST", "E201", "how-it-works--03-parser"],
    ["03", "Semantic", "symbols, types, permit, budget", "E301–E306", "how-it-works--04-semantic-analysis"],
    ["04", "IR + CFG", "three-address code, blocks", "", "how-it-works--05-ir-and-cfg"],
    ["05", "Taint", "data-flow fixed point", "E401", "how-it-works--06-taint-analysis", "safety"],
    ["06", "Approval", "dominators, guard blocks", "E501 E502", "how-it-works--07-approval-analysis", "safety"],
    ["07", "Optimizer", "fold, DCE, dedupe calls", "", "how-it-works--08-optimizer"],
    ["08", "Scheduler", "parallel rounds (stretch)", "", "how-it-works--11-parallel-scheduling", "stretch"],
    ["09", "Codegen", "IR → stack bytecode", "", "how-it-works--09-codegen-and-vm"],
    ["10", "VM", "tool registry, runtime guards", "E601–E604", "how-it-works--09-codegen-and-vm"],
  ];

  function showHome() {
    document.title = "AgentScript Docs";
    const errorCount = new Set(DATA.examples.flatMap((e) => [e.expect && e.expect.code, e.run && e.run.expect && e.run.expect.code]).filter(Boolean)).size;
    const card = (id, ic, title, text, cls = "") =>
      byId[id] ? `<a class="card ${cls}" href="${route(id)}"><div class="ic">${ic}</div><h3>${esc(title)}</h3><p>${esc(text)}</p></a>` : "";
    main.innerHTML = `<div class="home">
      <section class="hero">
        <div class="kicker">Compiler lab project</div>
        <h1>Agent programs that are <span class="grad">safe before they run</span>.</h1>
        <p class="lead">AgentScript is a tiny language whose compiler proves two things before any tool fires: untrusted data never reaches a privileged tool unsanitized, and no irreversible action happens without human approval.</p>
        <div class="cta">
          <a class="btn primary" href="${route("how-it-works--00-overview")}">Read the overview →</a>
          <a class="btn" href="${route("how-it-works--01-language")}">Language tour</a>
          <a class="btn" href="#/examples">Browse examples</a>
        </div>
        <div class="hero-code"><span class="k">agent</span> Assistant {
  <span class="k">permit</span> web_search, llm, send_email, confirm;
  <span class="k">budget</span> calls = <span class="t">5</span>;
  <span class="k">task</span> report(topic: <span class="t">string</span>) -> <span class="t">bool</span> {
    <span class="k">let</span> raw = web_search(topic);
    <span class="k">let</span> summary = llm(<span class="s">"Summarize: "</span> + raw[<span class="t">0</span>]);   <span class="c">// no sanitize!</span>
    <span class="k">if</span> (confirm(<span class="s">"Send report?"</span>)) { <span class="k">return</span> send_email(<span class="s">"me@example.com"</span>, summary); }
    <span class="k">return</span> false;
  }
}
<span class="bad">E401 [taint] 9:14: untrusted data from web_search (line 6)
  reaches privileged tool 'send_email' (line 9)</span>
<span class="ok">add sanitize(raw[0]) and it compiles: 5 of 5 calls, value true</span></div>
      </section>

      <div class="stats">
        <div class="stat hl"><div class="v">10</div><div class="l">pipeline stages, each with a printable artifact</div></div>
        <div class="stat"><div class="v">${errorCount}</div><div class="l">error codes with their own failing demo</div></div>
        <div class="stat"><div class="v">${DATA.examples.length}</div><div class="l">example programs</div></div>
        <div class="stat"><div class="v">${PAGES.length}</div><div class="l">documents on this site</div></div>
      </div>

      <h2 class="section-title">The pipeline</h2>
      <p class="section-sub">Click a stage to read how it works. Safety analyses run on the unoptimized program.</p>
      <div class="pipeline">${STAGES.map(([n, name, what, codes, id, cls]) =>
        `<a class="stage ${cls || ""}" href="${route(id)}"><div class="n">${n}</div><div class="name">${name}</div><div class="what">${what}</div><div class="codes">${codes}</div></a>`).join("")}</div>
      <div class="ordering"><b>Ordering rule.</b> Permission, budget, taint and approval checks run before the optimizer, so a guarantee never depends on what the optimizer removes.</div>

      <h2 class="section-title">Two headline guarantees</h2>
      <p class="section-sub">Plus permission lists and call budgets, all checked at compile time.</p>
      <div class="cards">
        ${card("how-it-works--06-taint-analysis", "T", "Taint tracking", "Forward data-flow analysis over the CFG: web_search and read_file results are untrusted until sanitize; a tainted argument to send_email or delete_file is E401 with the full source-to-sink path.", "bad")}
        ${card("how-it-works--07-approval-analysis", "A", "Approval-path checking", "Every irreversible call must sit in a block dominated by the true branch of a confirm result. Missing or one-branch confirms are E501 / E502 with an offending path.", "safe")}
        ${card("how-it-works--04-semantic-analysis", "B", "Permits and budgets", "Calling a tool outside permit is E305; more calls on the worst path than the budget is E306, and the VM enforces the budget again at runtime (E601).")}
      </div>

      <h2 class="section-title">Start reading</h2>
      <p class="section-sub">The source of truth is the corrected PRD; the how-it-works series explains each phase with real compiler output.</p>
      <div class="cards">
        ${card("readme", "i", "Docs index", "What each document is and the recommended reading order.")}
        ${card("prd", "§", "Product requirements", "Grammar, semantics, error taxonomy, milestones and the changes from the original PRD.")}
        ${card("implementation_plan", "M", "Implementation plan", "Milestones M1–M7, data structures, algorithms, API contract and traceability.")}
        ${card("presentation--demo-script", "▶", "Demo script", "The live demo, step by step, with the real output to expect.")}
        ${card("presentation--viva-notes", "?", "Viva notes", "Likely questions with prepared answers, one per phase and limitation.")}
        ${card("how-it-works--10-editor-and-api", "UI", "Editor and API", "How a Compile click flows through FastAPI, the pipeline and the phase tabs.")}
      </div>
    </div>`;
    markActive("home");
    tocEl.innerHTML = "";
    window.scrollTo(0, 0);
  }

  let exFilter = "all";

  function exKind(e) {
    if (e.expect) return "error";
    if (e.run && e.run.expect) return "runtime";
    return "valid";
  }

  function showExamples() {
    document.title = "Examples · AgentScript Docs";
    const filters = [["all", "All"], ["valid", "Valid"], ["error", "Compile errors"], ["runtime", "Runtime errors"]];
    const list = DATA.examples.filter((e) => exFilter === "all" || exKind(e) === exFilter);
    main.innerHTML = `<article class="doc" style="max-width:none">
      <div class="crumb"><span class="pill">Overview</span><span>examples/manifest.json</span></div>
      <h1>Example programs</h1>
      <p>One valid program per feature plus one failing program per error type. These are the files the editor's example picker loads and the tests check; the highlighted line is where the expected diagnostic points.</p>
      <div class="filters">${filters.map(([k, l]) => `<button data-f="${k}" class="${k === exFilter ? "on" : ""}">${l}</button>`).join("")}</div>
      <div class="ex-grid">${list.map((e) => {
        const exp = e.expect || (e.run && e.run.expect);
        const warn = (e.warnings || [])[0];
        const hitLine = exp ? exp.line : warn ? warn.line : -1;
        const badges = [];
        if (e.expect) badges.push(`<span class="badge err">${e.expect.code} ${e.expect.line}:${e.expect.col}</span>`);
        else badges.push(`<span class="badge ok">compiles</span>`);
        (e.warnings || []).forEach((w) => badges.push(`<span class="badge warn">${w.code} ${w.line}:${w.col}</span>`));
        if (e.run && e.run.expect) badges.push(`<span class="badge err">run → ${e.run.expect.code} ${e.run.expect.line}:${e.run.expect.col}</span>`);
        else if (e.run) badges.push(`<span class="badge ok">runs</span>`);
        const lines = e.source.replace(/\n$/, "").split("\n").map((ln, i) =>
          `<span class="${i + 1 === hitLine ? "hit" : ""}"><span class="ln">${i + 1}</span>${esc(ln)}</span>`).join("\n");
        const run = e.run ? `<p style="margin-top:6px"><code>run --task ${esc(e.run.task)} --args '${esc(JSON.stringify(e.run.args))}'</code></p>` : "";
        return `<div class="ex"><div class="ex-head"><div class="file">examples/${esc(e.file)}</div><h3>${esc(e.title)}</h3>
          <div style="margin:6px 0 8px">${badges.join("")}</div><p>${esc(e.description)}</p>${run}</div>
          <pre><code>${lines}</code></pre></div>`;
      }).join("")}</div></article>`;
    main.querySelectorAll(".filters button").forEach((b) => b.addEventListener("click", () => { exFilter = b.dataset.f; showExamples(); }));
    markActive("examples");
    tocEl.innerHTML = "";
  }

  // ---------------------------------------------------------------- router

  function router() {
    const hash = location.hash || "#/";
    document.body.classList.remove("nav-open");
    $("#scrim").hidden = true;
    const m = hash.match(/^#\/doc\/([^/]+)(?:\/(.+))?$/);
    if (m && byId[m[1]]) return showDoc(byId[m[1]], m[2] && decodeURIComponent(m[2]));
    if (hash.startsWith("#/examples")) return showExamples();
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
      html = html.replace(new RegExp("(" + t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "gi"), "<mark>$1</mark>");
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
      results.innerHTML = `<div class="sr-empty">No results for “${esc(q)}”.</div>`;
    } else {
      results.innerHTML = hits.slice(0, 14).map(({ e }) => {
        const i = e.body.toLowerCase().indexOf(terms[0]);
        const start = Math.max(0, i - 50);
        const snip = (start > 0 ? "…" : "") + e.body.slice(start, start + 150) + "…";
        return `<a href="${route(e.page.id, e.slug)}"><div class="sr-title">${highlight(e.heading, terms)}</div>
          <div class="sr-page">${esc(e.page.title)}</div><div class="sr-snip">${highlight(snip, terms)}</div></a>`;
      }).join("");
    }
    results.hidden = false;
  }

  searchBox.addEventListener("input", doSearch);
  searchBox.addEventListener("focus", doSearch);
  searchBox.addEventListener("keydown", (ev) => {
    const items = [...results.querySelectorAll("a")];
    if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
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
    if (ev.key === "/" && document.activeElement !== searchBox) {
      ev.preventDefault();
      searchBox.focus();
    }
  });

  // ----------------------------------------------------- theme, menu, progress

  function setTheme(t) {
    document.documentElement.setAttribute("data-theme", t);
    try { localStorage.setItem("as-docs-theme", t); } catch (e) { /* storage unavailable */ }
  }
  let saved = null;
  try { saved = localStorage.getItem("as-docs-theme"); } catch (e) { /* storage unavailable */ }
  setTheme(saved || (window.matchMedia && matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark"));
  $("#theme-btn").addEventListener("click", () => {
    setTheme(themeIsDark() ? "light" : "dark");
    router();
  });

  $("#menu-btn").addEventListener("click", () => {
    const open = !document.body.classList.contains("nav-open");
    document.body.classList.toggle("nav-open", open);
    $("#scrim").hidden = !open;
  });
  $("#scrim").addEventListener("click", () => {
    document.body.classList.remove("nav-open");
    $("#scrim").hidden = true;
  });

  const progress = $("#progress");
  window.addEventListener("scroll", () => {
    const h = document.documentElement.scrollHeight - innerHeight;
    progress.style.width = h > 0 ? (scrollY / h) * 100 + "%" : "0";
  }, { passive: true });

  buildSidebar();
  window.addEventListener("hashchange", router);
  router();
})();
