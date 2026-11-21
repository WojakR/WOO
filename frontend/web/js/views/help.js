// "Pomoc": the user manual and the text of the regulations (GET /api/knowledge…), with server-side search.
// Markdown is rendered by the small renderer below into DOM nodes – text only, never innerHTML, so HTML inside
// a document is shown as text and cannot run.
import { api } from "../api.js";
import { h, icon, replace, loading } from "../ui.js";

const KIND_LABEL = { PODRECZNIK: "Podręcznik użytkownika", PRZEPISY: "Przepisy", MATERIALY: "Materiały KPRM" };

export function slugify(text) {  // the same rule as app/api/knowledge.py::slugify
  return text.toLowerCase().replace(/ł/g, "l").normalize("NFD").replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}

// ---------------------------------------------------------------- inline: **bold**, *italic*, `code`, [text](url)
const INLINE = /(\*\*([^*]+)\*\*|\*([^*\s][^*]*)\*|`([^`]+)`|\[([^\]]+)\]\(([^)\s]+)\))/g;

function safeHref(url) {
  if (/^https?:\/\//i.test(url)) return { href: url, target: "_blank", rel: "noopener noreferrer" };
  if (url.startsWith("#/")) return { href: url };
  if (/^[a-z0-9-]+\.md$/i.test(url)) return { href: `#/pomoc/${url.replace(/\.md$/i, "")}` };
  return null;  // javascript:, data:, relative paths – shown as plain text
}

export function inline(text) {
  const out = [];
  let last = 0;
  for (const m of text.matchAll(INLINE)) {
    if (m.index > last) out.push(text.slice(last, m.index));
    if (m[2]) out.push(h("strong", {}, m[2]));
    else if (m[3]) out.push(h("em", {}, m[3]));
    else if (m[4]) out.push(h("code", {}, m[4]));
    else {
      const link = safeHref(m[6]);
      out.push(link ? h("a", link, m[5]) : `${m[5]} (${m[6]})`);
    }
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

// ---------------------------------------------------------------- blocks
function cells(line) {
  let t = line.trim();
  if (t.startsWith("|")) t = t.slice(1);
  if (t.endsWith("|")) t = t.slice(0, -1);
  return t.split("|").map((c) => c.trim());
}

const isSeparator = (line) => /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$/.test(line);

export function renderMarkdown(md) {
  const lines = md.replace(/\r\n?/g, "\n").split("\n");
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i += 1; continue; }
    const head = /^(#{1,4})\s+(.+)$/.exec(line);
    if (head) {
      const level = Math.min(head[1].length + 1, 5);  // the page has its own h1
      out.push(h(`h${level}`, { id: slugify(head[2]) }, inline(head[2].trim())));
      i += 1;
      continue;
    }
    if (line.trimStart().startsWith("|")) {
      const rows = [];
      while (i < lines.length && lines[i].trimStart().startsWith("|")) rows.push(lines[i++]);
      const hasHead = rows.length > 1 && isSeparator(rows[1]);
      const body = rows.filter((r) => !isSeparator(r)).map(cells);
      const width = Math.max(...body.map((r) => r.length));
      const tr = (r, tag) => h("tr", {}, Array.from({ length: width }, (_, k) => h(tag, {}, inline(r[k] ?? ""))));
      out.push(h("div", { class: "table-wrap" }, h("table", { class: "data compact md-table" },
        hasHead ? h("thead", {}, tr(body[0], "th")) : null,
        h("tbody", {}, (hasHead ? body.slice(1) : body).map((r) => tr(r, "td"))))));
      continue;
    }
    const bullet = /^\s*([-*]|\d+[.)])\s+(.*)$/.exec(line);
    if (bullet) {
      const ordered = /\d/.test(bullet[1]);
      const items = [];
      while (i < lines.length) {
        const m = /^\s*([-*]|\d+[.)])\s+(.*)$/.exec(lines[i]);
        if (!m || /\d/.test(m[1]) !== ordered) break;
        items.push(h("li", {}, inline(m[2])));
        i += 1;
      }
      out.push(h(ordered ? "ol" : "ul", {}, items));
      continue;
    }
    if (line.startsWith(">")) {
      const quote = [];
      while (i < lines.length && lines[i].startsWith(">")) quote.push(lines[i++].replace(/^>\s?/, ""));
      out.push(h("blockquote", {}, inline(quote.join(" "))));
      continue;
    }
    const para = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|\s*\||\s*([-*]|\d+[.)])\s|>)/.test(lines[i])) {
      para.push(lines[i++].trim());
    }
    if (!para.length) { para.push(lines[i++].trim()); }
    out.push(h("p", {}, inline(para.join(" "))));
  }
  return out;
}

// Highlight the first occurrence of `q` in the rendered document and scroll to it.
function markFirst(root, q) {
  const needle = q.toLowerCase();
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    const pos = node.data.toLowerCase().indexOf(needle);
    if (pos < 0) continue;
    const hit = node.splitText(pos);
    hit.splitText(q.length);
    const mark = h("mark", {}, hit.data);
    hit.replaceWith(mark);
    mark.scrollIntoView({ block: "center" });
    return true;
  }
  return false;
}

function params(hashPath) {
  const [, query = ""] = hashPath.split("?");
  return new URLSearchParams(query);
}

export async function renderHelp(view, hashPath) {
  const [, , slug] = hashPath.split("?")[0].split("/");
  const p = params(hashPath);
  if (slug) return renderDoc(view, decodeURIComponent(slug), p.get("q"), p.get("k"));
  const list = await api.knowledge();
  const results = h("div", { "aria-live": "polite" });
  const input = h("input", { type: "search", id: "help-q", placeholder: "Szukaj w podręczniku i przepisach, np. „sprzeciw”",
    value: p.get("szukaj") || "", style: { flex: "1 1 320px" } });
  async function run() {
    const q = input.value.trim();
    if (!q) { replace(results); return; }
    replace(results, loading("Szukam…"));
    const r = await api.knowledgeSearch(q);
    replace(results, r.komunikat ? h("p", { class: "small muted" }, r.komunikat)
      : r.wyniki.length ? h("ul", { class: "plain-list" }, r.wyniki.map((w) => h("li", {},
        h("a", { href: `#/pomoc/${w.slug}?q=${encodeURIComponent(q)}` }, w.tytul),
        h("span", { class: "small muted" }, ` · ${w.naglowek} · trafień: ${w.trafienia}`),
        h("div", { class: "small" }, w.fragment))))
        : h("p", { class: "small muted" }, "Nic nie znaleziono."));
  }
  const groups = Object.keys(KIND_LABEL).map((k) => [k, list.filter((d) => d.rodzaj === k)]).filter(([, d]) => d.length);
  replace(view,
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Pomoc"),
      h("p", {}, "Podręcznik użytkownika, treść rozporządzenia i ustawy oraz materiały KPRM."))),
    h("form", { class: "card card-pad row", style: { gap: "8px", flexWrap: "wrap", marginBottom: "16px" },
      onsubmit: (e) => { e.preventDefault(); run(); } },
      h("label", { for: "help-q", class: "sr-only" }, "Szukaj"), input,
      h("button", { class: "btn btn-primary", type: "submit" }, icon("search"), "Szukaj")),
    results,
    groups.map(([k, docs]) => h("section", { class: "card card-pad", style: { marginTop: "12px" } },
      h("h2", {}, KIND_LABEL[k]),
      h("ul", { class: "plain-list" }, docs.map((d) => h("li", {}, h("a", { href: `#/pomoc/${d.slug}` },
        icon(k === "PODRECZNIK" ? "book" : "clipboard"), " ", d.tytul)))))));
  if (input.value) run();
}

async function renderDoc(view, slug, q, anchor) {
  const doc = await api.knowledgeDoc(slug);
  const body = h("article", { class: "card card-pad md" }, renderMarkdown(doc.tresc));
  const toc = doc.naglowki.filter((x) => x.poziom >= 2).slice(0, 40);
  replace(view,
    h("div", { class: "page-head" }, h("div", {},
      h("a", { href: "#/pomoc", class: "small" }, icon("arrowLeft"), " Pomoc"),
      h("h1", {}, doc.tytul), h("p", {}, KIND_LABEL[doc.rodzaj] || ""))),
    toc.length ? h("nav", { class: "card card-pad", "aria-label": "Spis treści", style: { marginBottom: "12px" } },
      h("ul", { class: "plain-list toc" }, toc.map((t) => h("li", { style: { paddingLeft: `${(t.poziom - 2) * 14}px` } },
        h("a", { href: `#/pomoc/${slug}?k=${t.kotwica}` }, t.tekst))))) : null,
    body);
  if (q && !markFirst(body, q)) {
    body.prepend(h("p", { class: "notice notice-info" }, icon("info"), `Nie znaleziono „${q}” w tym dokumencie.`));
  } else if (anchor) {
    document.getElementById(anchor)?.scrollIntoView({ block: "start" });
  }
}
