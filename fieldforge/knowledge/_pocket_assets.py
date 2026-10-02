"""Fixed assets for the portable reader. No untrusted source text is executable."""

STYLE = """
:root { color-scheme: light; --bg: #f1f3ed; --paper: #fffefa; --ink: #1b3028;
 --muted: #52685b; --line: #d4ddd1; --accent: #28523e; --soft: #e4eddf; --reading: 1.12rem; }
:root[data-theme=dark] { color-scheme: dark; --bg: #15201b; --paper: #202e26;
 --ink: #e5ecdf; --muted: #b7c5b5; --line: #465649; --accent: #b4d5ae; --soft: #304333; }
:root[data-size=large] { --reading: 1.28rem; }
:root[data-size=largest] { --reading: 1.48rem; }
* { box-sizing: border-box; }
[hidden] { display: none !important; }
body { margin: 0; background: var(--bg); color: var(--ink); font: 16px/1.6 system-ui, sans-serif; }
button, input, select { font: inherit; color: inherit; }
a { color: var(--accent); }
a, button { touch-action: manipulation; }
button, input, select { min-height: 44px; border: 1px solid var(--line); border-radius: 9px;
 background: var(--paper); padding: 9px 13px; }
button, select { cursor: pointer; }
button:hover, .choice:hover { background: var(--soft); }
:focus-visible { outline: 3px solid var(--accent); outline-offset: 3px; }
.skip { position: absolute; top: -100px; left: 12px; padding: 10px; background: var(--paper); }
.skip:focus { top: 10px; z-index: 3; }
.wrap { max-width: 1280px; margin: auto; padding: 30px 36px; }
.top { display: flex; justify-content: space-between; align-items: center; gap: 16px; }
.brand { font-weight: 850; letter-spacing: .16em; font-size: .85rem; }
.badge { border: 1px solid var(--line); border-radius: 30px; padding: 6px 13px;
 font-size: .75rem; font-weight: 700; letter-spacing: .07em; }
.hero { border-bottom: 1px solid var(--line); padding: 28px 0 24px; }
h1 { font: 500 clamp(2.2rem, 5vw, 3.8rem)/1.08 Georgia, serif; margin: 0 0 15px; letter-spacing: -.025em; }
h1, h2, h3, p, dd, .choice { overflow-wrap: anywhere; }
h2 { font: 500 2rem/1.2 Georgia, serif; margin: 12px 0; }
h3 { margin: 0 0 12px; font-size: .85rem; letter-spacing: .08em; text-transform: uppercase; }
p { margin: 8px 0; }
.sub, .meta, .hint { color: var(--muted); font-size: .875rem; }
.hero .sub { max-width: 900px; }
#tools { display: flex; gap: 10px; align-items: end; flex-wrap: wrap; margin: 22px 0; }
#tools label { display: flex; flex-direction: column; gap: 5px; font-size: .82rem; font-weight: 700; }
#tools .search-field { flex: 1 1 260px; }
#query { width: 100%; }
#category { max-width: 250px; }
#results { margin: 16px 0; font-size: .9rem; }
.layout { display: grid; grid-template-columns: 300px minmax(0, 1fr); align-items: start; gap: 30px; }
#contents { min-width: 0; }
#contents ol { margin: 0; padding: 0; list-style: none; }
.enhanced #contents ol { max-height: 70vh; overflow: auto; padding-right: 5px; }
#contents li { border-bottom: 1px solid var(--line); }
.choice { display: block; text-decoration: none; padding: 16px 14px; min-height: 60px; border-radius: 8px; }
.choice[aria-current=true] { background: var(--soft); box-shadow: inset 3px 0 var(--accent); }
.choice strong { display: block; font-size: .96rem; line-height: 1.4; }
.choice span { display: block; margin-top: 5px; color: var(--muted); font-size: .8rem; }
#reading { min-width: 0; }
.entry { background: var(--paper); border: 1px solid var(--line); border-radius: 12px;
 padding: 30px 34px; margin-bottom: 26px; }
.eyebrow { text-transform: uppercase; color: var(--muted); letter-spacing: .11em; font-size: .73rem; font-weight: 750; }
.warning { font-size: .83rem; padding: 12px 15px; background: var(--soft); border-left: 3px solid var(--accent); margin: 18px 0; }
.provenance { border-block: 1px solid var(--line); margin: 18px 0 24px; padding: 10px 0; }
.provenance summary { cursor: pointer; min-height: 44px; padding-top: 8px; font-size: .85rem; font-weight: 700; }
dl { display: grid; grid-template-columns: 145px minmax(0, 1fr); font-size: .8rem; gap: 7px 15px; }
dt { font-weight: 700; } dd { margin: 0; white-space: pre-wrap; }
.article-body { font: var(--reading)/1.78 Georgia, serif; white-space: pre-wrap; overflow-wrap: anywhere;
 unicode-bidi: plaintext; tab-size: 4; }
.reader-actions { display: flex; justify-content: space-between; gap: 12px; margin-top: 22px; flex-wrap: wrap; }
.empty { padding: 28px; border: 1px dashed var(--line); border-radius: 12px; background: var(--paper); }
footer { border-top: 1px solid var(--line); margin-top: 24px; padding-top: 18px; font-size: .78rem; color: var(--muted); }
@media (max-width: 760px) {
 .wrap { padding: 20px 16px; } .hero { padding-top: 22px; } .badge { font-size: .65rem; }
 .layout { grid-template-columns: 1fr; gap: 18px; } .enhanced #contents ol { max-height: 275px; }
 .entry { padding: 23px 19px; } #tools { gap: 9px; } #category { max-width: 100%; }
 #tools label:not(.search-field) { flex: 1 1 140px; } .article-body { line-height: 1.7; }
 dl { grid-template-columns: 1fr; gap: 3px; } dd { margin-bottom: 7px; }
}
@media print {
 @page { margin: 18mm; }
 :root, :root[data-theme=dark] { --paper: white; --bg: white; --ink: black; --muted: #333;
 --line: #888; --accent: black; --soft: white; --reading: 12pt; color-scheme: light; }
 .wrap { padding: 0; } .layout { display: block; } .entry { border: 0; padding: 0; break-before: page; }
 .entry h2 { font-size: 22pt; } .hero h1 { font-size: 26pt; }
 #tools, #contents, .reader-actions, .skip, #results, #fallback { display: none !important; }
 .enhanced .entry { break-before: auto; }
 .article-body { font-size: 12pt; } h2, h3 { break-after: avoid; } p { orphans: 3; widows: 3; }
}
"""

SCRIPT = r"""(() => {
  "use strict";
  const doc = document;
  const root = doc.documentElement;
  const entries = Array.from(doc.querySelectorAll(".entry"));
  const choices = Array.from(doc.querySelectorAll(".choice"));
  const tools = doc.getElementById("tools");
  const query = doc.getElementById("query");
  const category = doc.getElementById("category");
  const results = doc.getElementById("results");
  const empty = doc.getElementById("empty");
  const fallback = doc.getElementById("fallback");
  const fold = value => value.normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  let active = null;
  let timer;
  try {
    // Only escaped DOM text is indexed. No JSON evaluation or HTML insertion.
    const records = entries.map((node, index) => ({
      node, link: choices[index], id: node.id,
      title: node.querySelector("h2").textContent,
      category: node.querySelector(".category").textContent,
      text: fold(node.querySelector("h2").textContent + "\n" + node.querySelector(".article-body").textContent)
    }));
    const categories = Array.from(new Set(records.map(item => item.category))).sort();
    categories.forEach(value => {
      const option = doc.createElement("option");
      option.value = value;
      option.textContent = value;
      category.append(option);
    });
    const choose = (record, focus) => {
      active = record;
      records.forEach(item => {
        item.node.hidden = item !== record;
        item.link.setAttribute("aria-current", String(item === record));
      });
      if (record && focus) record.node.querySelector("h2").focus();
    };
    const filter = () => {
      clearTimeout(timer);
      const words = fold(query.value.slice(0, 240)).trim().split(/\s+/).filter(Boolean);
      const found = records.filter(item => (!category.value || item.category === category.value)
        && words.every(word => item.text.includes(word)));
      const membership = new Set(found);
      records.forEach(item => { item.link.parentElement.hidden = !membership.has(item); });
      choose(membership.has(active) ? active : (found[0] || null), false);
      empty.hidden = found.length > 0;
      results.textContent = found.length + " of " + records.length + " references shown. "
        + (words.length ? "Literal title/body matches, not an AI answer." : "Search happens only inside this file.");
    };
    const fromHash = (focus) => {
      const id = window.location.hash.slice(1);
      const item = records.find(record => record.id === id);
      if (!item) return; // Numeric generated IDs only, never selectors built from untrusted hashes.
      if (item.link.parentElement.hidden) {
        query.value = ""; category.value = ""; filter();
      }
      choose(item, focus);
    };
    records.forEach(item => {
      item.link.addEventListener("click", () => choose(item, true));
      item.node.querySelector(".back").addEventListener("click", () => {
        doc.getElementById("contents").focus(); doc.getElementById("contents").scrollIntoView();
      });
      item.node.querySelector(".print").addEventListener("click", () => {
        choose(item, false);
        // Keep source information visible on the explicitly requested paper copy.
        item.node.querySelector(".provenance").open = true;
        window.print();
      });
    });
    query.addEventListener("input", () => {
      clearTimeout(timer); timer = setTimeout(filter, 120);
    });
    tools.addEventListener("submit", event => { event.preventDefault(); filter(); });
    category.addEventListener("change", filter);
    doc.getElementById("reset").addEventListener("click", () => {
      query.value = ""; category.value = ""; filter(); query.focus();
    });
    doc.getElementById("size").addEventListener("change", event => {
      root.dataset.size = event.target.value;
    });
    const theme = doc.getElementById("theme");
    theme.addEventListener("click", () => {
      const dark = root.dataset.theme !== "dark";
      root.dataset.theme = dark ? "dark" : "light";
      theme.setAttribute("aria-pressed", String(dark));
      theme.textContent = dark ? "Light view" : "Dark view";
    });
    window.addEventListener("hashchange", () => fromHash(true));
    filter(); fromHash(false);
    root.classList.add("enhanced");
    tools.hidden = false;
    doc.querySelectorAll(".reader-actions").forEach(node => { node.hidden = false; });
    fallback.textContent = "Read-only offline copy. Search and display preferences stay in this view and are not saved. "
      + "Use a browser that opens local HTML; a file-preview app may show only the static text.";
  } catch (_error) {
    // A disabled/unsupported script never makes source text inaccessible.
    root.classList.remove("enhanced"); tools.hidden = true; empty.hidden = true;
    entries.forEach(node => { node.hidden = false; });
    choices.forEach(node => { node.parentElement.hidden = false; });
    doc.querySelectorAll(".reader-actions").forEach(node => { node.hidden = true; });
    results.textContent = "Interactive reader unavailable. All captured articles are shown below.";
  }
})();"""
