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
    const KIND = { DWIE_NEGATYWNE: "Dwie kolejne oceny negatywne", STOPIEN_OBLIGATORYJNY: "Obligatoryjny kolejny stopień",
      WNIOSEK_O_STOPIEN: "Wniosek o kolejny stopień służbowy" };
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
        : "Osoby, których oceny widzisz, oraz Ty.")),
      isHr ? h("button", { class: "btn btn-primary", type: "button",
        onclick: () => employeeDialog(null, (saved) => { location.hash = `#/pracownicy/${saved.pracownik.id}`; }) },
      icon("users"), "Dodaj pracownika") : null),
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
  const isHr = ctx.me.rola === "KADRY";
  replace(view,
    h("a", { class: "back", href: "#/pracownicy" }, icon("arrowLeft"), "Pracownicy"),
    h("div", { class: "eval-head" }, h("div", { class: "title" }, avatar(p.imie, p.nazwisko, "avatar-lg"),
      h("h1", {}, `${p.imie} ${p.nazwisko}`), h("span", { class: "badge badge-sheet" }, `Arkusz ${p.arkusz}`)),
      isHr ? h("div", { class: "row", style: { gap: "8px" } },
        h("button", { class: "btn", type: "button", onclick: () => employeeDialog(id, () => renderCard(view, ctx, id)) },
          icon("pencil"), "Edytuj dane"),
        h("button", { class: "btn", type: "button", onclick: () => removalDialog(id, `${p.imie} ${p.nazwisko}`) },
          "Usuń dane pracownika")) : null),
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


// ---------------------------------------------------------------- HR: add / edit a person (the rules of the HR import)
function errorText(e) {
  return e.walidacje?.length ? `${e.message} ${e.walidacje.map((w) => w.komunikat).join(" ")}` : e.message;
}

async function employeeDialog(id, onSaved) {
  const [form, people] = await Promise.all([
    id ? api.employeeForm(id) : Promise.resolve({}),
    api.employees("na_strone=200").then((d) => d.pozycje.map((x) => x.pracownik)).catch(() => []),
  ]);
  const f = { urzednik_mianowany: false, ...form };
  const input = (key, label, type = "text", extra = {}) => h("label", { class: "stack", style: { gap: "4px" } },
    h("span", { class: "small" }, label),
    h("input", { type, value: f[key] ?? "", ...extra, oninput: (e) => { f[key] = e.target.value || null; } }));
  const check = (key, label) => h("label", { class: "row small", style: { gap: "6px" } },
    h("input", { type: "checkbox", checked: Boolean(f[key]), onchange: (e) => { f[key] = e.target.checked; } }), label);
  const boss = h("select", { "aria-label": "Przełożony (oceniający)", onchange: (e) => { f.przelozony = e.target.value ? Number(e.target.value) : null; } },
    h("option", { value: "" }, "— brak (np. kierownik urzędu) —"),
    people.filter((x) => x.id !== id).map((x) => h("option", { value: x.id, selected: f.przelozony === x.id },
      `${x.nazwisko} ${x.imie} – ${x.stanowisko || ""}`)));
  const sheet = h("select", { "aria-label": "Arkusz", onchange: (e) => { f.arkusz = e.target.value || null; } },
    h("option", { value: "" }, "z roli (A – kierownik urzędu, B – kieruje zespołem, C – pozostali)"),
    ["A", "B", "C"].map((a) => h("option", { value: a, selected: f.arkusz === a }, `Arkusz ${a}`)));
  const startCycle = h("input", { type: "checkbox" });
  const out = h("div");
  const dlg = h("dialog", { class: "modal", "aria-labelledby": "emp-h", style: { width: "min(760px, calc(100vw - 32px))" } },
    h("form", { method: "dialog", class: "stack", style: { gap: "10px", minWidth: "0" }, onsubmit: async (e) => {
      e.preventDefault();
      const body = { ...f, stopien_sluzbowy: f.stopien_sluzbowy ? Number(f.stopien_sluzbowy) : null };
      try {
        const saved = id ? await api.updateEmployee(id, body) : await api.addEmployee(body, startCycle.checked);
        toast(id ? "Zapisano dane pracownika." : `Dodano pracownika (${saved.dane.id}).`
          + (saved.uruchomiony_cykl ? " Uruchomiono cykl oceny." : ""));
        dlg.close();
        onSaved(saved);
      } catch (err) {
        replace(out, h("p", { class: "notice notice-bad" }, icon("alert"), errorText(err)));
      }
    } },
      h("h2", { id: "emp-h" }, id ? "Edycja danych pracownika" : "Nowy pracownik"),
      h("p", { class: "small muted" }, "Te same zasady co w imporcie z systemu kadrowego: wymagane imię, nazwisko i stanowisko; "
        + "przełożony musi istnieć, bez pętli w strukturze; stopień służbowy tylko dla urzędnika."
        + (id ? " Zmianę przełożonego osoby z oceną w toku wprowadza się przez „Zmiana oceniającego”." : "")),
      h("div", { class: "grid-fields" },
        input("imie", "Imię", "text", { required: true }), input("nazwisko", "Nazwisko", "text", { required: true }),
        input("stanowisko", "Stanowisko", "text", { required: true }), input("komorka", "Komórka organizacyjna"),
        input("urzad", "Urząd"), input("email", "E-mail", "email"),
        h("label", { class: "stack", style: { gap: "4px" } }, h("span", { class: "small" }, "Przełożony (oceniający)"), boss),
        h("label", { class: "stack", style: { gap: "4px" } }, h("span", { class: "small" }, "Arkusz oceny"), sheet),
        input("stopien_sluzbowy", "Stopień służbowy (1–9)", "number", { min: 1, max: 9 }),
        input("data_zatrudnienia", "Data zatrudnienia (na czas nieokreślony)", "date"),
        input("data_ostatniej_oceny", "Data ostatniej oceny", "date"),
        input("data_przyznania_stopnia", "Data przyznania stopnia", "date"),
        input("data_zakonczenia_zatrudnienia", "Data ustania zatrudnienia", "date")),
      input("opis_stanowiska", "Opis stanowiska (pomaga asystentowi dobrać kryteria)"),
      h("div", { class: "row", style: { gap: "16px", flexWrap: "wrap" } },
        check("urzednik_mianowany", "Urzędnik służby cywilnej (mianowany)"),
        check("kieruje_zespolem", "Kieruje zespołem"), check("kierownik_urzedu", "Kierownik urzędu / dyrektor generalny"),
        id ? null : h("label", { class: "row small", style: { gap: "6px" } }, startCycle, "Uruchom cykl oceny")),
      out,
      h("div", { class: "row", style: { justifyContent: "flex-end", gap: "8px" } },
        h("button", { class: "btn", type: "button", onclick: () => dlg.close() }, "Anuluj"),
        h("button", { class: "btn btn-primary", type: "submit" }, icon("save"), "Zapisz"))));
  dlg.addEventListener("close", () => dlg.remove());
  document.body.append(dlg);
  dlg.showModal();
}

// ---------------------------------------------------------------- HR: delete the person's data (archive stays)
async function removalDialog(id, name) {
  const end = h("input", { type: "date", "aria-label": "Data ustania stosunku pracy" });
  const confirmBox = h("input", { type: "checkbox" });
  const out = h("div");
  const go = h("button", { class: "btn btn-danger", type: "button", disabled: true }, "Usuń dane");
  async function check() {
    try {
      const plan = await api.removalPlan(id, end.value);
      if (!end.value && plan.data_ustania_zatrudnienia) end.value = plan.data_ustania_zatrudnienia;
      go.disabled = !plan.mozna_usunac;
      replace(out, plan.mozna_usunac
        ? h("div", { class: "notice notice-info" },
          h("p", {}, `Do archiwum (akta osobowe, przechowywane 10 lat od końca roku ustania zatrudnienia): ${plan.do_archiwum.length} ocen.`),
          h("p", {}, `Usunięte zostaną: cykle bez sporządzonej oceny (${plan.do_usuniecia.length}), notatki robocze, nieobecności, `
            + "zastępstwa, dane RCP, ustawienia i konta logowania. W systemie zostaje tylko zapis bez danych osobowych."))
        : h("div", { class: "notice notice-bad" }, h("p", {}, "Nie można jeszcze usunąć danych:"),
          h("ul", { class: "small" }, plan.przeszkody.map((x) => h("li", {}, x)))));
    } catch (err) {
      replace(out, h("p", { class: "notice notice-bad" }, errorText(err)));
    }
  }
  go.onclick = async () => {
    if (!confirmBox.checked) { toast("Zaznacz potwierdzenie usunięcia.", "bad"); return; }
    try {
      const r = await api.removeEmployee(id, { data_ustania_zatrudnienia: end.value || null, zatwierdzam: true });
      toast(`Usunięto dane: ${name}. Oceny w archiwum: ${r.do_archiwum.length}.`);
      dlg.close();
      location.hash = "#/pracownicy";
    } catch (err) {
      replace(out, h("p", { class: "notice notice-bad" }, errorText(err)));
    }
  };
  end.addEventListener("change", check);
  const dlg = h("dialog", { class: "modal", "aria-labelledby": "rm-h", style: { width: "min(600px, calc(100vw - 32px))" } },
    h("div", { class: "stack", style: { gap: "10px", minWidth: "0" } },
      h("h2", { id: "rm-h" }, `Usunięcie danych pracownika – ${name}`),
      h("p", { class: "small muted" }, "Po ustaniu stosunku pracy. Zamknięte oceny trafiają najpierw do archiwum (część akt osobowych), "
        + "od daty ustania zatrudnienia liczy się okres ich przechowywania. Operacji nie można cofnąć."),
      h("label", { class: "stack", style: { gap: "4px" } }, h("span", { class: "small" }, "Data ustania stosunku pracy"), end),
      out,
      h("label", { class: "row small", style: { gap: "6px" } }, confirmBox, "Potwierdzam usunięcie danych tej osoby"),
      h("div", { class: "row", style: { justifyContent: "flex-end", gap: "8px" } },
        h("button", { class: "btn", type: "button", onclick: () => dlg.close() }, "Anuluj"), go)));
  dlg.addEventListener("close", () => dlg.remove());
  document.body.append(dlg);
  dlg.showModal();
  check();
}
