// "Pracownicy" – the people the user may see (the server decides: AccessPolicy) and one person's card with the
// history of evaluations. Nothing is computed here: statuses, results and deadlines come from the API.
import { api } from "../api.js";
import { h, icon, replace, fmtDate, fmtNumber, avatar, toast, loading } from "../ui.js";
import { STATUS_LABEL, LEVEL_LABEL, personName } from "../labels.js";

const RESULT = { POZYTYWNA: ["badge-ok", "pozytywna"], NEGATYWNA: ["badge-bad", "negatywna"] };
const OBJECTION = { ZLOZONY: "złożony", UWZGLEDNIONY: "uwzględniony", NIEUWZGLEDNIONY: "nieuwzględniony" };
const EMPLOYMENT = { URZEDNIK: "urzędnik służby cywilnej", PRACOWNIK: "pracownik służby cywilnej" };

function resultBadge(w) {
  if (!w) return h("span", { class: "muted" }, "–");
  const [cls, text] = RESULT[w];
  return h("span", { class: `badge ${cls}` }, text);
}

export async function renderEmployees(view, ctx, employeeId = null) {
  if (employeeId) return renderCard(view, ctx, employeeId);
  const isHr = ctx.me.rola === "KADRY";
  const f = { komorka: "", arkusz: "", status: "", wynik: "", szukaj: "", strona: 1 };
  const R = { filters: h("div", { class: "card filters" }), list: h("div", { class: "card" }), import: h("div"), tasks: h("div") };

  async function renderTasks() {
    if (!isHr) return;
    const tasks = await api.hrTasks().catch(() => []);
    if (!tasks.length) return;
    const KIND = { DWIE_NEGATYWNE: "Dwie kolejne oceny negatywne", STOPIEN_OBLIGATORYJNY: "Obligatoryjny kolejny stopień" };
    replace(R.tasks, h("section", { class: "card", style: { marginBottom: "16px" } },
      h("div", { class: "card-head" }, h("div", {}, h("h2", {}, "Zadania działu kadr"),
        h("p", {}, "Skutki kolejnych ocen okresowych – system niczego nie rozstrzyga sam."))),
      h("ul", { class: "plain-list", style: { padding: "0 20px 18px" } }, tasks.map((t) => h("li", {},
        h("div", {}, h("strong", {}, `${KIND[t.rodzaj] || t.rodzaj}: ${personName(t.oceniany)}`),
          h("div", { class: "small muted" }, t.tresc)),
        t.evaluation_id ? h("a", { class: "btn btn-sm", href: `#/ocena/${t.evaluation_id}` }, "Otwórz ocenę") : null)))));
  }

  async function load() {
    replace(R.list, h("div", { class: "card-pad" }, loading()));
    const q = new URLSearchParams(Object.entries(f).filter(([, v]) => v !== "" && v !== null));
    q.set("na_strone", "25");
    const data = await api.employees(q.toString());
    renderFilters(data.komorki);
    renderList(data);
  }

  const sel = (key, label, options) => h("label", {}, h("span", { class: "sr-only" }, label),
    h("select", { "aria-label": label, onchange: (e) => { f[key] = e.target.value; f.strona = 1; load(); } },
      h("option", { value: "" }, label), options.map(([v, t]) => h("option", { value: v, selected: f[key] === v }, t))));

  function renderFilters(units) {
    if (R.filters.childElementCount) return;  // built once – keeps focus while typing
    let timer = null;
    replace(R.filters,
      h("div", { class: "search" }, icon("search"),
        h("input", { type: "search", placeholder: "Szukaj: nazwisko, stanowisko", "aria-label": "Szukaj pracownika",
          oninput: (e) => { clearTimeout(timer); timer = setTimeout(() => { f.szukaj = e.target.value; f.strona = 1; load(); }, 250); } })),
      sel("komorka", "Komórka: wszystkie", units.map((u) => [u, u])),
      sel("arkusz", "Arkusz: wszystkie", ["A", "B", "C"].map((a) => [a, `Arkusz ${a}`])),
      sel("status", "Bieżąca ocena: każda", Object.entries(STATUS_LABEL)),
      sel("wynik", "Ostatni wynik: każdy", [["POZYTYWNA", "pozytywna"], ["NEGATYWNA", "negatywna"]]));
  }

  function renderList(data) {
    const pages = Math.max(1, Math.ceil(data.razem / data.na_strone));
    replace(R.list,
      h("div", { class: "card-head" }, h("div", {}, h("h2", {}, "Pracownicy"), h("p", {}, `Osób: ${data.razem}`))),
      data.pozycje.length
        ? h("div", { class: "table-wrap" }, h("table", { class: "data" },
          h("caption", { class: "sr-only" }, "Lista pracowników"),
          h("thead", {}, h("tr", {}, ["", "Pracownik", "Stanowisko", "Komórka", "Arkusz", "Przełożony", "Bieżąca ocena",
            "Ostatni wynik", ""].map((c) => h("th", { scope: "col" }, c)))),
          h("tbody", {}, data.pozycje.map((r) => {
            const p = r.pracownik;
            const cur = r.biezaca_ocena;
            return h("tr", {},
              h("td", {}, avatar(p.imie, p.nazwisko)),
              h("td", {}, h("strong", {}, `${p.imie} ${p.nazwisko}`)),
              h("td", {}, p.stanowisko || "–"),
              h("td", {}, p.komorka || "–"),
              h("td", {}, h("span", { class: "badge badge-sheet" }, p.arkusz)),
              h("td", {}, p.przelozony ? personName(p.przelozony) : "–"),
              h("td", {}, cur ? h("a", { href: `#/ocena/${cur.evaluation_id}` }, STATUS_LABEL[cur.status]) : h("span", { class: "muted" }, "brak")),
              h("td", {}, resultBadge(r.ostatnia_ocena?.wynik)),
              h("td", {}, h("a", { class: "btn btn-sm", href: `#/pracownicy/${p.id}`, "aria-label": `Karta: ${p.imie} ${p.nazwisko}` },
                "Karta", icon("chevronRight"))));
          }))))
        : h("p", { class: "empty" }, "Brak pracowników spełniających wybrane filtry."),
      pages > 1 ? h("div", { class: "row card-pad", style: { justifyContent: "flex-end" } },
        h("button", { class: "btn btn-sm", type: "button", disabled: f.strona <= 1, onclick: () => { f.strona -= 1; load(); } }, "Poprzednia"),
        h("span", { class: "small muted" }, `Strona ${f.strona} z ${pages}`),
        h("button", { class: "btn btn-sm", type: "button", disabled: f.strona >= pages, onclick: () => { f.strona += 1; load(); } }, "Następna"))
        : null);
  }

  function renderImport() {
    if (!isHr) return;
    const file = h("input", { type: "file", accept: ".csv,.xlsx", "aria-label": "Plik z systemu kadrowego" });
    const cycles = h("input", { type: "checkbox" });
    const out = h("div");
    const send = async (preview) => {
      if (!file.files[0]) { toast("Wybierz plik CSV lub XLSX.", "bad"); return; }
      try {
        const r = await api.importEmployees(file.files[0], { podglad: preview, uruchom_cykle: cycles.checked });
        replace(out,
          h("p", { class: `notice ${r.problemy.length ? "notice-bad" : "notice-info"}` },
            r.zapisano ? `Zapisano. Dodani: ${r.dodani.length}, zaktualizowani: ${r.zaktualizowani.length}, uruchomione cykle: ${r.uruchomione_cykle.length}.`
              : `${preview ? "Podgląd" : "Nie zapisano"}: wierszy ${r.liczba_wierszy}, nowi ${r.dodani.length}, do aktualizacji ${r.zaktualizowani.length}, błędy ${r.problemy.length}.`),
          r.problemy.length ? h("ul", { class: "small" }, r.problemy.map((p) => h("li", {}, `Wiersz ${p.wiersz}${p.id ? ` (${p.id})` : ""}: ${p.komunikat}`))) : null);
        if (r.zapisano) load();
      } catch (e) {
        replace(out, h("p", { class: "notice notice-bad" }, icon("alert"), e.message));
      }
    };
    replace(R.import, h("details", { class: "card audit" },
      h("summary", { class: "card-head" }, h("div", {}, h("h2", {}, "Import z systemu kadrowego"),
        h("p", {}, "Plik CSV lub XLSX: stanowiska, przełożeni, status urzędnika, stopień, e-mail. Najpierw podgląd."))),
      h("div", { class: "card-pad stack" },
        file,
        h("label", { class: "row small" }, cycles, "Uruchom cykl oceny dla osób bez otwartej oceny"),
        h("div", { class: "row" },
          h("button", { class: "btn", type: "button", onclick: () => send(true) }, "Podgląd"),
          h("button", { class: "btn btn-primary", type: "button", onclick: () => send(false) }, icon("check"), "Importuj")),
        out)));
  }

  replace(view,
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Pracownicy"),
      h("p", {}, isHr ? "Wszyscy pracownicy urzędu z danymi kadrowymi i historią ocen."
        : "Osoby, których oceny widzisz, oraz Ty."))),
    R.tasks, R.filters, R.list, R.import);
  renderImport();
  renderTasks();
  await load();
}

async function renderCard(view, ctx, id) {
  const [card, history] = await Promise.all([api.employee(id), api.employeeHistory(id)]);
  const absences = await api.absences(id).catch(() => null);
  const p = card.pracownik;
  const cur = card.biezaca_ocena;
  const field = (label, value) => h("div", {}, h("div", { class: "small muted" }, label), h("div", {}, value || "–"));
  replace(view,
    h("a", { class: "back", href: "#/pracownicy" }, icon("arrowLeft"), "Pracownicy"),
    h("div", { class: "eval-head" }, h("div", { class: "title" }, avatar(p.imie, p.nazwisko, "avatar-lg"),
      h("h1", {}, `${p.imie} ${p.nazwisko}`), h("span", { class: "badge badge-sheet" }, `Arkusz ${p.arkusz}`))),
    h("div", { class: "stack" },
      h("section", { class: "card card-pad" }, h("h2", {}, "Dane kadrowe"),
        h("div", { class: "grid-fields" },
          field("Stanowisko", p.stanowisko), field("Komórka", p.komorka),
          field("Przełożony (oceniający)", p.przelozony ? personName(p.przelozony) : null),
          field("Status", EMPLOYMENT[p.typ_zatrudnienia]),
          p.typ_zatrudnienia === "URZEDNIK" ? field("Stopień służbowy", p.stopien_sluzbowy) : null,
          field("E-mail", p.email))),
      h("section", { class: "card card-pad" }, h("h2", {}, "Bieżąca ocena"),
        cur ? h("p", {}, `${STATUS_LABEL[cur.status]} · termin oceny ${fmtDate(cur.termin_oceny)} · `,
          h("a", { href: `#/ocena/${cur.evaluation_id}` }, "otwórz ocenę"))
          : h("p", { class: "muted" }, "Brak otwartego cyklu oceny.")),
      h("section", { class: "card" }, h("div", { class: "card-head" }, h("div", {}, h("h2", {}, "Historia ocen"),
        h("p", {}, "Od najstarszej; pierwsza pozycja może pochodzić z danych kadrowych sprzed systemu."))),
      history.length ? h("div", { class: "table-wrap" }, h("table", { class: "data rules" },
        h("thead", {}, h("tr", {}, ["Sporządzona", "Arkusz", "Oceniający", "Okres", "Średnia", "Poziom", "Wynik", "Sprzeciw", "Status", ""]
          .map((c) => h("th", { scope: "col" }, c)))),
        h("tbody", {}, history.map((x) => h("tr", {},
          h("td", { class: "nowrap" }, fmtDate(x.data_sporzadzenia)),
          h("td", {}, x.arkusz || "–"),
          h("td", {}, x.oceniajacy ? personName(x.oceniajacy) : "–"),
          h("td", { class: "nowrap" }, x.okres_od ? `${fmtDate(x.okres_od)} – ${fmtDate(x.okres_do)}` : "–"),
          h("td", { class: "num" }, x.srednia !== null ? fmtNumber(x.srednia) : "–"),
          h("td", {}, x.poziom ? LEVEL_LABEL[x.poziom] : "–"),
          h("td", {}, resultBadge(x.wynik)),
          h("td", {}, x.sprzeciw ? OBJECTION[x.sprzeciw] : "–"),
          h("td", {}, x.zrodlo === "DANE_KADROWE" ? h("span", { class: "small muted" }, "z danych kadrowych")
            : x.zrodlo === "IMPORT" ? h("span", { class: "badge badge-idle" }, "zaimportowana") : STATUS_LABEL[x.status]),
          h("td", {}, x.evaluation_id ? h("a", { class: "btn btn-sm", href: `#/ocena/${x.evaluation_id}` }, "Otwórz") : null))))))
        : h("p", { class: "empty" }, "Brak ocen.")),
      absences ? h("section", { class: "card card-pad" }, h("h2", {}, "Nieobecności"),
        absences.length ? h("ul", {}, absences.map((a) => h("li", {}, `${fmtDate(a.od)} – ${fmtDate(a.do)} (${a.typ})`)))
          : h("p", { class: "muted" }, "Brak zarejestrowanych nieobecności."),
        h("a", { class: "btn btn-sm", href: `#/nieobecnosci/${p.id}` }, "Zarządzaj nieobecnościami")) : null));
}
