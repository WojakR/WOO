// Reports for HR / managers: progress (T17), outcomes with charts (T18), training needs (T19).
// Every number comes from /api/reports/*; charts are inline SVG (no libraries, works offline) with a data table.
import { api, currentUserId } from "../api.js";
import { h, icon, replace, fmtDate, fmtNumber, toast, loading } from "../ui.js";
import { STATUS_LABEL } from "../labels.js";

const SVG = "http://www.w3.org/2000/svg";

function svg(tag, attrs = {}, ...children) {
  const el = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined && v !== false) el.setAttribute(k, String(v));
  for (const c of children.flat()) if (c) el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return el;
}

// Horizontal bars: [{ label, value, text, hidden }]. Hidden groups are drawn as a dashed outline.
function barChart(items, { max = null, title, onPick = null, selected = null } = {}) {
  const shown = items.filter((i) => !i.hidden);
  const top = max ?? Math.max(1, ...shown.map((i) => i.value || 0));
  const rowH = 30, labelW = 210, barW = 300, width = labelW + barW + 70;
  const chart = svg("svg", { viewBox: `0 0 ${width} ${items.length * rowH + 6}`, role: "img", "aria-label": title,
    class: "chart", width: "100%" });
  items.forEach((it, i) => {
    const y = i * rowH + 4;
    const w = it.hidden ? barW : Math.max(2, (barW * (it.value || 0)) / top);
    const g = svg("g", { class: `chart-row${onPick && !it.hidden ? " clickable" : ""}${selected === it.label ? " selected" : ""}` },
      svg("title", {}, it.hidden ? `${it.label}: ukryte (za mała grupa)` : `${it.label}: ${it.text ?? it.value}`),
      svg("text", { x: labelW - 8, y: y + 17, "text-anchor": "end", class: "chart-label" },
        it.label.length > 30 ? `${it.label.slice(0, 29)}…` : it.label),
      it.hidden
        ? svg("rect", { x: labelW, y: y + 4, width: barW, height: 18, rx: 3, class: "chart-bar-hidden" })
        : svg("rect", { x: labelW, y: y + 4, width: w, height: 18, rx: 3, class: "chart-bar" }),
      svg("text", { x: labelW + (it.hidden ? barW : w) + 6, y: y + 17, class: "chart-value" },
        it.hidden ? "ukryte" : (it.text ?? it.value)));
    if (onPick && !it.hidden) {
      g.setAttribute("tabindex", "0");
      g.addEventListener("click", () => onPick(it));
      g.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onPick(it); } });
    }
    chart.append(g);
  });
  return chart;
}

// Trend between cycles: one point per year (average), hidden years left out of the line.
function lineChart(points, title) {
  const width = 520, height = 180, pad = 36;
  const shown = points.filter((p) => !p.hidden);
  const chart = svg("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": title, class: "chart", width: "100%" });
  const x = (i) => pad + (points.length === 1 ? (width - 2 * pad) / 2 : (i * (width - 2 * pad)) / (points.length - 1));
  const y = (v) => height - pad - ((v - 1) / 8) * (height - 2 * pad);  // scale 1–9
  for (const v of [1, 3, 5, 7, 9]) {
    chart.append(svg("line", { x1: pad, x2: width - pad, y1: y(v), y2: y(v), class: "chart-grid" }),
      svg("text", { x: pad - 8, y: y(v) + 4, "text-anchor": "end", class: "chart-label" }, v));
  }
  const pts = points.map((p, i) => (p.hidden ? null : [x(i), y(p.srednia)])).filter(Boolean);
  if (pts.length > 1) chart.append(svg("polyline", { points: pts.map((p) => p.join(",")).join(" "), class: "chart-line" }));
  points.forEach((p, i) => {
    chart.append(svg("text", { x: x(i), y: height - 10, "text-anchor": "middle", class: "chart-label" }, p.nazwa));
    if (!p.hidden) {
      chart.append(svg("circle", { cx: x(i), cy: y(p.srednia), r: 5, class: "chart-dot" },
        svg("title", {}, `${p.nazwa}: średnia ${p.srednia}, ${p.osoby} os.`)));
    }
  });
  if (!shown.length) chart.append(svg("text", { x: width / 2, y: height / 2, "text-anchor": "middle", class: "chart-label" }, "brak danych do pokazania"));
  return chart;
}

function table(head, rows) {
  return h("div", { class: "table-wrap" }, h("table", { class: "data compact" },
    h("thead", {}, h("tr", {}, head.map((x) => h("th", { scope: "col" }, x)))),
    h("tbody", {}, rows.length ? rows.map((r) => h("tr", {}, r.map((c) => h("td", {}, c ?? "–"))))
      : h("tr", {}, h("td", { colspan: head.length, class: "muted" }, "Brak danych.")))));
}

function stat(label, value, sub) {
  return h("div", { class: "card stat" }, h("span", { class: "stat-label" }, label),
    h("span", { class: "stat-value" }, value ?? "–"), sub ? h("span", { class: "stat-sub" }, sub) : null);
}

function dataTable(summary, head, rows) {
  return h("details", { class: "chart-data" }, h("summary", {}, summary), table(head, rows));
}

export async function renderReports(view, ctx) {
  const f = { rok: ctx.year !== "all" ? ctx.year : "", komorka: "", poziom: null, wynik: null };
  const R = { filters: h("div"), progress: h("div"), outcomes: h("div"), training: h("div") };
  const q = (extra = {}) => {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries({ rok: f.rok, komorka: f.komorka, ...extra })) if (v) p.set(k, v);
    const s = p.toString();
    return s ? `?${s}` : "";
  };

  replace(view,
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Raporty"),
      h("p", {}, "Postęp i wyniki ocen okresowych w zakresie, który widzisz (kadry – cały urząd, przełożony – swój zespół)."))),
    R.filters, R.progress, R.outcomes, R.training);

  async function loadProgress() {
    replace(R.progress, loading());
    const p = await api.report("progress", q());
    if (!R.filters.childElementCount) renderFilters(p.dostepne_komorki);
    const units = p.komorki.map((u) => [u.komorka, u.objeci_ocena, u.cykle, u.sporzadzone, u.w_toku, u.po_terminie,
      u.w_terminie_proc === null ? "–" : `${fmtNumber(u.w_terminie_proc, 0)}%`]);
    replace(R.progress, h("section", { class: "stack", "aria-labelledby": "rep-prog-h" },
      h("h2", { id: "rep-prog-h" }, `Postęp ocen – ${p.zakres}`),
      h("div", { class: "stats" },
        stat("Objęci oceną", p.objeci_ocena, p.bez_cyklu ? `${p.bez_cyklu} bez rozpoczętego cyklu` : "wszyscy mają cykl"),
        stat("Ocen sporządzonych", p.sporzadzone, `z ${p.cykle} cykli`),
        stat("W toku", p.w_toku, `${p.oczekuje_na_ocenianego} czeka na ocenianego`),
        stat("Po terminie", p.po_terminie, "kryteria, ocena lub sprzeciw"),
        stat("W terminie", p.w_terminie_proc === null ? "–" : `${fmtNumber(p.w_terminie_proc, 0)}%`, "sporządzonych ocen"),
        stat("Status", Object.keys(p.statusy).length, "różnych etapów")),
      h("div", { class: "card card-pad" }, h("h3", {}, "Rozkład statusów"),
        barChart(Object.entries(p.statusy).map(([k, v]) => ({ label: STATUS_LABEL[k] || k, value: v })), { title: "Rozkład statusów ocen" }),
        h("h3", { style: { marginTop: "14px" } }, "Średni czas etapów (dni)"),
        table(["Etap", "Średnio dni"], Object.entries(p.sredni_czas_etapow_dni).map(([k, v]) => [STATUS_LABEL[k] || k, fmtNumber(v, 1)]))),
      h("div", { class: "card" }, h("div", { class: "card-head" }, h("h3", {}, "Komórki organizacyjne")),
        table(["Komórka", "Objęci", "Cykle", "Sporządzone", "W toku", "Po terminie", "W terminie"], units))));
  }

  async function loadOutcomes() {
    replace(R.outcomes, loading());
    const o = await api.report("outcomes", q({ poziom: f.poziom, wynik: f.wynik }));
    const pick = (it) => { f.poziom = f.poziom === it.label ? null : it.label; loadOutcomes(); };
    const body = [];
    if (o.ukryte) {
      body.push(h("p", { class: "notice notice-info" }, icon("info"),
        `Ocenionych osób w tym zakresie: ${o.ocenieni}. Wyniki pokazujemy dla grup co najmniej ${o.minimalna_grupa} osób, `
        + "żeby nie dało się rozpoznać pojedynczych pracowników."));
    } else {
      body.push(h("div", { class: "card card-pad" }, h("h3", {}, "Rozkład poziomów ocen"),
        h("p", { class: "small muted" }, "Kliknij słupek, żeby zobaczyć listę pracowników z tym poziomem."),
        barChart(o.poziomy.map((p) => ({ label: p.poziom, value: p.liczba })), { title: "Rozkład poziomów ocen", onPick: pick, selected: f.poziom }),
        dataTable("Dane wykresu", ["Poziom", "Liczba"], o.poziomy.map((p) => [p.poziom, p.liczba]))));
    }
    const groupRows = (list) => list.map((g) => [g.nazwa, g.osoby, g.ukryte ? "ukryte" : fmtNumber(g.srednia),
      g.ukryte || g.pozytywne_proc === null ? "–" : `${fmtNumber(g.pozytywne_proc, 0)}%`]);
    body.push(h("div", { class: "grid-2" },
      h("div", { class: "card card-pad" }, h("h3", {}, "Średnia ocena cząstkowa – kryteria"),
        barChart(o.kryteria.map((g) => ({ label: g.nazwa, value: g.srednia, text: g.srednia === null ? "" : fmtNumber(g.srednia), hidden: g.ukryte })),
          { max: 9, title: "Średnie oceny cząstkowe według kryteriów" }),
        dataTable("Dane wykresu", ["Kryterium", "Osoby", "Średnia"], groupRows(o.kryteria).map((r) => r.slice(0, 3)))),
      h("div", { class: "card card-pad" }, h("h3", {}, "Porównanie komórek – średnia"),
        barChart(o.komorki.map((g) => ({ label: g.nazwa, value: g.srednia, text: g.srednia === null ? "" : fmtNumber(g.srednia), hidden: g.ukryte })),
          { max: 9, title: "Średnia ocen według komórek" }),
        dataTable("Dane wykresu", ["Komórka", "Osoby", "Średnia", "Pozytywne"], groupRows(o.komorki)))));
    body.push(h("div", { class: "card card-pad" }, h("h3", {}, "Trend między cyklami (średnia według roku sporządzenia)"),
      lineChart(o.trend, "Trend średniej oceny według roku"),
      dataTable("Dane wykresu", ["Rok", "Osoby", "Średnia", "Pozytywne"], groupRows(o.trend))));
    if (f.poziom || f.wynik) {
      body.push(h("div", { class: "card" }, h("div", { class: "card-head" },
        h("h3", {}, `Pracownicy: ${f.poziom || ""}${f.wynik ? ` (${f.wynik})` : ""}`),
        h("button", { class: "btn btn-sm", type: "button", onclick: () => { f.poziom = null; f.wynik = null; loadOutcomes(); } }, icon("x"), "Wyczyść filtr")),
      table(["Pracownik", "Komórka", "Poziom", "Średnia", "Wynik", "Data oceny"], o.pracownicy.map((p) => [
        p.evaluation_id ? h("a", { href: `#/ocena/${p.evaluation_id}` }, p.pracownik) : p.pracownik,
        p.komorka, p.poziom, fmtNumber(p.srednia), p.wynik, fmtDate(p.data_oceny)]))));
    }
    replace(R.outcomes, h("section", { class: "stack", "aria-labelledby": "rep-out-h", style: { marginTop: "18px" } },
      h("h2", { id: "rep-out-h" }, "Wyniki ocen"), body));
  }

  async function loadTraining() {
    replace(R.training, loading());
    const t = await api.report("training-needs", q());
    replace(R.training, h("section", { class: "card", "aria-labelledby": "rep-tr-h", style: { marginTop: "18px" } },
      h("div", { class: "card-head" }, h("h2", { id: "rep-tr-h" }, "Potrzeby szkoleniowe"),
        h("button", { class: "btn btn-sm", type: "button", onclick: downloadCsv }, icon("download"), "Eksport CSV")),
      h("div", { class: "card-pad stack" },
        h("p", { class: "small muted" }, `Oceny cząstkowe poniżej ${t.prog} pkt w ostatniej ocenie każdej osoby.`),
        h("div", { class: "proposal" }, h("div", { class: "proposal-head" },
          h("span", { class: `badge ${t.zrodlo === "AI" ? "badge-ai" : "badge-idle"}` }, icon("sparkles"),
            t.zrodlo === "AI" ? "Rekomendacja asystenta" : "Rekomendacja (szablon)")),
          h("div", { class: "proposal-text" }, t.rekomendacja)),
        h("h3", {}, "Ranking kryteriów"),
        table(["Kryterium", "Obszar szkoleniowy", "Niskie oceny", "Ocenieni"], t.ranking.map((r) => [r.kryterium, r.obszar, r.niskie_oceny, r.ocenieni])),
        h("h3", {}, "Osoby"),
        table(["Pracownik", "Komórka", "Potrzeby", "Wnioski IPRZ"], t.osoby.map((p) => [
          p.evaluation_id ? h("a", { href: `#/ocena/${p.evaluation_id}` }, p.pracownik) : p.pracownik, p.komorka,
          p.potrzeby.map((n) => `${n.area} (${n.criterion}: ${n.score})`).join("; "), p.wnioski_iprz || "–"])))));
  }

  async function downloadCsv() {
    try {
      const res = await fetch(`/api/reports/training-needs.csv${q()}`, { headers: { "X-User-Id": currentUserId() || "" } });
      if (!res.ok) throw new Error((await res.json().catch(() => null))?.komunikat || "Nie udało się pobrać pliku.");
      const a = h("a", { href: URL.createObjectURL(await res.blob()), download: "potrzeby-szkoleniowe.csv" });
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) { toast(e.message, "bad"); }
  }

  function renderFilters(units) {
    const year = h("select", { id: "rep-year", onchange: (e) => { f.rok = e.target.value; reload(); } },
      [["", "Wszystkie lata"], ["2026", "2026"], ["2027", "2027"], ["2028", "2028"]].map(([v, l]) => h("option", { value: v, selected: f.rok === v }, l)));
    const unit = h("select", { id: "rep-unit", onchange: (e) => { f.komorka = e.target.value; reload(); } },
      h("option", { value: "" }, "Wszystkie komórki"), units.map((u) => h("option", { value: u }, u)));
    replace(R.filters, h("div", { class: "card card-pad row", style: { gap: "16px", flexWrap: "wrap", marginBottom: "16px" } },
      h("label", { for: "rep-year", class: "row", style: { gap: "6px" } }, "Rok terminu oceny", year),
      h("label", { for: "rep-unit", class: "row", style: { gap: "6px" } }, "Komórka", unit)));
  }

  async function reload() {
    try {
      await Promise.all([loadProgress(), loadOutcomes(), loadTraining()]);
    } catch (e) {
      replace(R.progress, h("div", { class: "card card-pad notice notice-bad" }, icon("alert"), e.message));
      replace(R.outcomes); replace(R.training);
    }
  }
  await reload();
}
