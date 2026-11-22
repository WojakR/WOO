// Screen 2 – overview of evaluations (evaluator: own subordinates, HR: whole office).
import { api } from "../api.js";
import { h, icon, replace, fmtDate, avatar, daysLeftText, daysWord, toast } from "../ui.js";
import { STAGES, STATUS_LABEL, WHO_LABEL, personName } from "../labels.js";

const FUNNEL_COLORS = ["#9fb4d6", "#6f8fc4", "#3f6db3", "#1f5fbf", "#163f80", "#1d7444"];

export async function renderOverview(view, ctx) {
  const data = await api.dashboard();
  const all = data.pozycje.filter((i) => ctx.year === "all" || !i.termin_oceny || i.termin_oceny.startsWith(ctx.year));
  const state = { unit: "", q: "", stage: "", result: "", due: "", sort: { key: "termin", dir: 1 } };

  const units = [...new Set(all.map((i) => i.komorka).filter(Boolean))].sort((a, b) => a.localeCompare(b, "pl"));
  const statsBox = h("div");
  const funnelBox = h("div");
  const tableBox = h("div", { class: "card" });
  const attentionBox = h("div", { class: "card" });

  const scoped = () => all.filter((i) => !state.unit || i.komorka === state.unit);

  function filtered() {
    const q = state.q.trim().toLocaleLowerCase("pl");
    return scoped().filter((i) => {
      if (q && !`${personName(i.oceniany)} ${i.oceniany.stanowisko || ""}`.toLocaleLowerCase("pl").includes(q)) return false;
      if (state.stage === "BRAK" && i.status) return false;
      if (state.stage && state.stage !== "BRAK" && i.status !== state.stage) return false;
      if (state.result === "BRAK" && i.wynik) return false;
      if (state.result && state.result !== "BRAK" && i.wynik !== state.result) return false;
      if (state.due === "PO" && i.pilnosc !== "PO_TERMINIE") return false;
      if (state.due === "30" && !(i.dni_do_terminu !== null && i.dni_do_terminu >= 0 && i.dni_do_terminu <= 30)) return false;
      if (state.due === "LATER" && !(i.dni_do_terminu !== null && i.dni_do_terminu > 30)) return false;
      return true;
    });
  }

  function update() {
    renderStats(statsBox, scoped());
    renderFunnel(funnelBox, scoped());
    renderTable(tableBox, filtered(), state, update);
    renderAttention(attentionBox, scoped());
  }

  const select = (label, key, options) =>
    h("label", { class: "small muted row", style: { gap: "6px" } }, label,
      h("select", { onchange: (e) => { state[key] = e.target.value; update(); } },
        options.map(([v, t]) => h("option", { value: v }, t))));

  // the user's own evaluation (as the evaluated person): a person who evaluates nobody sees only that
  const own = data.moje || [];
  if (ctx.me.rola !== "KADRY" && !ctx.me.czy_oceniajacy && !data.pozycje.length) {
    return replace(view,
      h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Moja ocena okresowa"),
        h("p", {}, "Twoja ocena: etap, termin i to, czy teraz czeka na Ciebie jakiś krok."))),
      own.length ? ownEvaluations(own) : h("section", { class: "card card-pad" },
        h("p", { class: "empty" }, "Nie masz jeszcze rozpoczętej oceny okresowej.")));
  }

  const title = ctx.me.rola === "KADRY" ? "Oceny okresowe – wszystkie urzędy" : `Oceny okresowe – ${ctx.me.urzad}`;
  const lead = ctx.me.rola === "KADRY"
    ? "Stan ocen okresowych w urzędach (dane przykładowe). Kliknij „Otwórz”, aby zobaczyć arkusz."
    : "Oceny osób, które oceniasz. Termin, etap i to, kto ma teraz wykonać krok.";

  replace(view,
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, title), h("p", {}, lead))),
    own.length ? ownEvaluations(own) : null,
    h("div", { class: "card filters", role: "search" },
      select("Komórka", "unit", [["", "Wszystkie komórki"], ...units.map((u) => [u, u])]),
      h("div", { class: "search" }, icon("search"),
        h("label", { class: "sr-only", for: "q" }, "Szukaj pracownika"),
        h("input", { id: "q", type: "search", placeholder: "Szukaj po nazwisku lub stanowisku…",
          oninput: (e) => { state.q = e.target.value; update(); } })),
      select("Etap", "stage", [["", "Wszystkie"], ...STAGES.map((s) => [s.status, s.short]), ["ZAKONCZONA", "Zakończone"], ["BRAK", "Nierozpoczęte"]]),
      select("Wynik", "result", [["", "Wszystkie"], ["POZYTYWNA", "Pozytywna"], ["NEGATYWNA", "Negatywna"], ["BRAK", "Brak wyniku"]]),
      select("Termin", "due", [["", "Wszystkie"], ["PO", "Po terminie"], ["30", "≤ 30 dni"], ["LATER", "Później"]])),
    statsBox,
    funnelBox,
    h("div", { class: "with-aside overview-grid" }, tableBox, h("div", { class: "aside" }, attentionBox)));
  update();
}

function pct(n, total) {
  return total ? `${Math.round((n / total) * 100)}%` : "0%";
}

function renderStats(box, items) {
  // one row per evaluation (a finished one + the cycle that followed it): the stage counters use each person's
  // latest evaluation in the selected years, so they add up to the number of people
  const latest = [...new Map(items.map((i) => [i.oceniany.id, i])).values()];
  const total = latest.length;
  const done = latest.filter((i) => i.status === "ZAKONCZONA").length;
  const notStarted = latest.filter((i) => !i.evaluation_id).length;
  const running = total - done - notStarted;
  const overdue = items.filter((i) => i.pilnosc === "PO_TERMINIE").length;
  const negative = items.filter((i) => i.wynik === "NEGATYWNA").length;
  const stat = (label, value, sub, cls = "", ic = null) =>
    h("div", { class: `card stat ${cls}` },
      h("div", { class: "stat-label" }, ic ? icon(ic) : null, label),
      h("div", { class: "stat-value" }, value),
      h("div", { class: "stat-sub" }, sub));
  replace(box, h("section", { class: "stats", "aria-label": "Podsumowanie" },
    stat("Objęci oceną", total, "osoby w wybranym zakresie"),
    stat("Zakończone", done, `${pct(done, total)} objętych oceną`, "ok", "circleCheck"),
    stat("W toku", running, `${pct(running, total)} objętych oceną`),
    stat("Nierozpoczęte", notStarted, `${pct(notStarted, total)} objętych oceną`),
    stat("Po terminie", overdue, overdue ? "wymaga pilnej reakcji" : "brak przekroczeń", overdue ? "bad" : "", overdue ? "alert" : null),
    stat("Oceny negatywne", negative, "sporządzone w tym cyklu", negative ? "bad" : "", negative ? "circleX" : null)));
}

function renderFunnel(box, items) {
  const counts = STAGES.map((s, idx) => ({
    label: idx === 0 ? "Wyznaczenie kryteriów" : s.short,
    sub: idx === 0 ? "w tym nierozpoczęte" : "",
    n: items.filter((i) => i.status === s.status || (idx === 0 && !i.status)).length,
  }));
  counts.push({ label: "Zakończone", sub: "", n: items.filter((i) => i.status === "ZAKONCZONA").length });
  const total = items.length;
  replace(box, h("section", { class: "card funnel", "aria-labelledby": "funnel-h" },
    h("div", { class: "row", style: { justifyContent: "space-between" } },
      h("h2", { id: "funnel-h" }, "Etapy procesu"),
      h("span", { class: "small muted" }, `razem ${total}`)),
    h("div", { class: "funnel-bar", role: "img",
      "aria-label": counts.map((c) => `${c.label}: ${c.n}`).join(", ") },
      counts.map((c, i) => c.n ? h("span", { style: { flex: String(c.n), background: FUNNEL_COLORS[i] }, title: `${c.label}: ${c.n}` }) : null)),
    h("div", { class: "funnel-legend" },
      counts.map((c, i) => h("div", { class: "funnel-item" },
        h("span", {}, h("span", { class: "sw", style: { background: FUNNEL_COLORS[i] }, "aria-hidden": "true" }), c.label),
        h("strong", {}, c.n),
        c.sub ? h("span", { class: "small muted" }, c.sub) : null)))));
}

const COLUMNS = [
  { key: "name", label: "Imię i nazwisko", get: (i) => personName(i.oceniany) },
  { key: "position", label: "Stanowisko", get: (i) => i.oceniany.stanowisko || "" },
  { key: "unit", label: "Komórka", get: (i) => i.komorka || "" },
  { key: "sheet", label: "Arkusz", get: (i) => i.arkusz },
  { key: "stage", label: "Etap", get: (i) => (i.status ? STAGES.findIndex((s) => s.status === i.status) : -1) },
  { key: "termin", label: "Termin", get: (i) => (i.dni_do_terminu ?? 99999) },
  { key: "result", label: "Wynik", get: (i) => i.wynik || "" },
  { key: "who", label: "Kto działa", get: (i) => i.kto_dziala },
];

function resultBadge(w) {
  if (w === "POZYTYWNA") return h("span", { class: "badge badge-ok" }, icon("circleCheck"), "pozytywna");
  if (w === "NEGATYWNA") return h("span", { class: "badge badge-bad" }, icon("circleX"), "negatywna");
  return h("span", { class: "muted" }, "–");
}

function stageBadge(i) {
  if (!i.status) return h("span", { class: "badge badge-idle" }, icon("circle"), "Nierozpoczęta");
  if (i.status === "ZAKONCZONA") return h("span", { class: "badge badge-ok" }, icon("check"), "Zakończona");
  return h("span", { class: "badge badge-info" }, STATUS_LABEL[i.status]);
}

function deadlineCell(i) {
  if (!i.termin) return h("span", { class: "muted" }, "–");
  if (i.dni_do_terminu === null || i.dni_do_terminu === undefined) return h("span", { class: "num" }, fmtDate(i.termin));
  const cls = i.pilnosc === "PO_TERMINIE" ? "badge-bad" : i.pilnosc === "OK" ? "" : "badge-warn";
  const text = i.dni_do_terminu < 0 ? `${-i.dni_do_terminu} ${daysWord(i.dni_do_terminu)} po terminie`
    : `${i.dni_do_terminu} ${daysWord(i.dni_do_terminu)}`;
  return h("span", { class: "row", style: { gap: "6px", flexWrap: "nowrap" } },
    h("span", { class: "num nowrap" }, fmtDate(i.termin)),
    cls ? h("span", { class: `badge ${cls}` }, i.pilnosc === "PO_TERMINIE" ? icon("alert") : icon("clock"), text)
      : h("span", { class: "small muted nowrap" }, `(${text})`));
}

function renderTable(box, items, state, update) {
  const { key, dir } = state.sort;
  const col = COLUMNS.find((c) => c.key === key);
  const rows = [...items].sort((a, b) => {
    const x = col.get(a), y = col.get(b);
    return (typeof x === "number" ? x - y : String(x).localeCompare(String(y), "pl")) * dir;
  });
  const th = (c) => h("th", { scope: "col", "aria-sort": c.key === key ? (dir > 0 ? "ascending" : "descending") : false },
    h("button", { type: "button", onclick: () => {
      state.sort = { key: c.key, dir: c.key === key ? -dir : 1 };
      update();
    } }, c.label, icon(c.key === key ? (dir > 0 ? "chevronUp" : "chevronDown") : "sort")));

  replace(box,
    h("div", { class: "card-head" },
      h("div", {}, h("h2", {}, "Pracownicy"), h("p", {}, `Pozycji: ${rows.length}`))),
    rows.length
      ? h("div", { class: "table-wrap" }, h("table", { class: "data" },
        h("caption", { class: "sr-only" }, "Lista ocen okresowych"),
        h("thead", {}, h("tr", {}, h("th", { scope: "col" }, h("span", { class: "sr-only" }, "Inicjały")),
          COLUMNS.map(th), h("th", { scope: "col" }, h("span", { class: "sr-only" }, "Akcje")))),
        h("tbody", {}, rows.map((i) => h("tr", { class: i.pilnosc === "PO_TERMINIE" ? "overdue" : "" },
          h("td", {}, avatar(i.oceniany.imie, i.oceniany.nazwisko)),
          h("td", {}, h("strong", {}, personName(i.oceniany))),
          h("td", {}, i.oceniany.stanowisko || "–"),
          h("td", {}, i.komorka || "–"),
          h("td", {}, h("span", { class: "badge badge-sheet" }, i.arkusz)),
          h("td", {}, stageBadge(i)),
          h("td", {}, deadlineCell(i)),
          h("td", {}, resultBadge(i.wynik)),
          h("td", {}, WHO_LABEL[i.kto_dziala] || "–"),
          h("td", {}, i.evaluation_id
            ? h("a", { class: "btn btn-sm", href: `#/ocena/${i.evaluation_id}`,
              "aria-label": `Otwórz ocenę: ${personName(i.oceniany)}` }, "Otwórz", icon("chevronRight"))
            : h("button", { class: "btn btn-sm btn-primary", type: "button", onclick: () => startCycle(i),
              "aria-label": `Rozpocznij ocenę: ${personName(i.oceniany)}` }, icon("forward"), "Rozpocznij ocenę"))))))
      )
      : h("p", { class: "empty" }, "Brak pozycji spełniających wybrane filtry."));
}

// Start a new evaluation cycle (UC1). Sheet (suggested from the position), criteria and deadlines: the server.
async function startCycle(i, ctx) {
  const date = h("input", { type: "date", id: "start-date" });
  const err = h("div");
  let sug = null;
  try { sug = await api.sheetSuggestion(i.oceniany.id); } catch { /* the server still decides */ }
  const sheetSel = h("select", { id: "start-sheet" }, ["A", "B", "C"].map((x) =>
    h("option", { value: x, selected: x === (sug?.sugerowany || i.arkusz) }, `Arkusz ${x}`)));
  const sheetWhy = h("input", { type: "text", id: "start-sheet-why", placeholder: "Uzasadnienie innego arkusza" });
  const go = h("button", { class: "btn btn-primary", type: "submit" }, icon("check"), "Rozpocznij ocenę");
  const dlg = h("dialog", { class: "modal", "aria-labelledby": "start-h" },
    h("form", { method: "dialog", onsubmit: async (e) => {
      e.preventDefault();
      go.disabled = true;
      try {
        const other = sug && sug.mozna_zmienic && sheetSel.value !== sug.sugerowany;
        const ev = await api.startEvaluation({ oceniany_id: i.oceniany.id, data_poczatku_cyklu: date.value || null,
          ...(other ? { arkusz: sheetSel.value, uzasadnienie_arkusza: sheetWhy.value } : {}) });
        dlg.close();
        toast(`Rozpoczęto ocenę: ${personName(i.oceniany)}. Termin wyznaczenia kryteriów: ${fmtDate(ev.czesc_i.termin_wyznaczenia_kryteriow)}.`);
        location.hash = `#/ocena/${ev.id}`;
      } catch (e2) {
        replace(err, h("p", { class: "notice notice-bad" }, icon("alert"), e2.message));
        go.disabled = false;
      }
    } },
    h("h2", { id: "start-h" }, `Rozpocznij ocenę okresową – ${personName(i.oceniany)}`),
    sug ? h("div", { class: "stack", style: { gap: "6px", marginTop: "8px" } },
      h("p", {}, h("strong", {}, `Podpowiedź: arkusz ${sug.sugerowany}. `), sug.powod),
      sug.ostrzezenie ? h("p", { class: "notice notice-bad" }, icon("alert"), sug.ostrzezenie) : null,
      sug.mozna_zmienic ? h("div", { class: "row", style: { gap: "8px", flexWrap: "wrap" } },
        h("label", { for: "start-sheet", class: "sr-only" }, "Arkusz"), sheetSel,
        h("label", { for: "start-sheet-why", class: "sr-only" }, "Uzasadnienie"), sheetWhy) : null)
      : h("p", { class: "small muted" }, `Arkusz ${i.arkusz}.`),
    h("p", { class: "small muted" }, "Kryteria obowiązkowe, oceniający i terminy ustali system na podstawie danych kadrowych."),
    h("label", { for: "start-date", class: "stack", style: { gap: "4px", margin: "14px 0" } },
      h("span", { style: { fontWeight: 650 } }, "Początek cyklu oceny (opcjonalnie)"),
      date,
      h("span", { class: "small muted" }, "Puste pole: data poprzedniej oceny, a gdy jej nie ma – dzisiejsza data (zatrudnienie).")),
    err,
    h("div", { class: "row", style: { justifyContent: "flex-end", gap: "8px" } },
      h("button", { class: "btn", type: "button", onclick: () => dlg.close() }, "Anuluj"), go)));
  dlg.addEventListener("close", () => dlg.remove());
  document.body.append(dlg);
  dlg.showModal();
}

// "Moja ocena": the user's own evaluations; the one waiting for the user's step comes first and stands out.
function ownEvaluations(items) {
  const rows = [...items].sort((a, b) => (b.kto_dziala === "OCENIANY") - (a.kto_dziala === "OCENIANY")
    || (b.evaluation_id || 0) - (a.evaluation_id || 0));
  const waiting = rows.filter((i) => i.kto_dziala === "OCENIANY").length;
  return h("section", { class: "card", style: { marginBottom: "16px" }, "aria-labelledby": "own-h" },
    h("div", { class: "card-head" }, h("div", {},
      h("h2", { id: "own-h" }, "Moja ocena"),
      h("p", {}, waiting ? "Czeka na Ciebie krok w ocenie okresowej." : "Nic nie czeka teraz na Ciebie."))),
    h("ul", { class: "plain-list" }, rows.map((i) => {
      const mine = i.kto_dziala === "OCENIANY";
      return h("li", { class: "row", style: { gap: "12px", flexWrap: "wrap", alignItems: "center" } },
        stageBadge(i),
        mine ? h("span", { class: "badge badge-warn" }, icon("alert"), "Czeka na Ciebie") : null,
        h("span", {}, mine ? i.nastepny_krok || ""
          : WHO_LABEL[i.kto_dziala] && i.kto_dziala !== "NIKT" ? `Teraz działa: ${WHO_LABEL[i.kto_dziala]}` : ""),
        h("span", { style: { marginLeft: "auto" } }, deadlineCell(i)),
        i.wynik ? resultBadge(i.wynik) : null,
        i.evaluation_id ? h("a", { class: `btn btn-sm ${mine ? "btn-primary" : ""}`, href: `#/ocena/${i.evaluation_id}`,
          "aria-label": `Otwórz moją ocenę (${STATUS_LABEL[i.status] || "ocena"})` }, "Otwórz", icon("chevronRight")) : null);
    })));
}

function renderAttention(box, items) {
  const upcoming = items.filter((i) => i.dni_do_terminu !== null && i.dni_do_terminu !== undefined)
    .sort((a, b) => a.dni_do_terminu - b.dni_do_terminu).slice(0, 3);
  const waiting = items.filter((i) => i.kto_dziala === "OCENIANY");
  const objections = items.filter((i) => i.status === "SPRZECIW");
  const notStarted = items.filter((i) => !i.evaluation_id);

  const person = (i, right) => h("li", {},
    i.evaluation_id ? h("a", { href: `#/ocena/${i.evaluation_id}` }, personName(i.oceniany)) : h("span", {}, personName(i.oceniany)),
    right);
  const section = (title, count, list, emptyText) => h("li", {},
    h("div", { class: "attention-head" }, h("span", {}, title),
      h("span", { class: `badge ${count ? "badge-warn" : "badge-idle"}` }, count)),
    list.length ? h("ul", { class: "attention-list" }, list) : h("p", { class: "small muted", style: { marginTop: "4px" } }, emptyText));

  replace(box,
    h("div", { class: "card-head" }, h("h2", {}, "Wymaga uwagi")),
    h("ul", { class: "attention" },
      section("Najbliższe terminy", upcoming.length,
        upcoming.map((i) => person(i, h("span", { class: `small nowrap ${i.dni_do_terminu < 0 ? "" : "muted"}`,
          style: i.dni_do_terminu < 0 ? { color: "var(--bad)", fontWeight: 600 } : {} },
        `${fmtDate(i.termin)} · ${daysLeftText(i.dni_do_terminu)}`))), "Brak zbliżających się terminów."),
      section("Czekają na potwierdzenie pracownika", waiting.length,
        waiting.map((i) => person(i, h("span", { class: "small muted" }, STATUS_LABEL[i.status]))), "Nikt nie czeka."),
      section("Nierozpoczęte cykle oceny", notStarted.length,
        notStarted.map((i) => person(i, h("span", { class: "small muted" }, `arkusz ${i.arkusz}`))), "Wszystkie cykle rozpoczęte."),
      section("Sprzeciwy w toku", objections.length,
        objections.map((i) => person(i, h("span", { class: "small muted" }, "sprzeciw"))), "Brak sprzeciwów.")));
}
