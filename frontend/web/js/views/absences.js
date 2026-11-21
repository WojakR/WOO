// UC8 – "Nieobecności": register an absence of the evaluated person. Whether and how far the evaluation
// deadline moves is decided by the server (art. 81 ust. 7); this screen only shows what it returns.
import { api } from "../api.js";
import { h, icon, replace, fmtDate, avatar, toast } from "../ui.js";
import { ABSENCE_LABEL, STATUS_LABEL, personName } from "../labels.js";

export async function renderAbsences(view, ctx, employeeId) {
  const data = await api.dashboard();
  const people = data.pozycje.filter((i) => i.evaluation_id && i.status !== "ZAKONCZONA");
  const s = { id: employeeId || people[0]?.oceniany.id || null, list: [], changes: [], last: null, deadline: null };
  const item = () => people.find((i) => i.oceniany.id === s.id);

  const R = { list: h("div", { class: "card" }), form: h("div", { class: "card" }), result: h("div") };

  async function load() {
    const it = item();
    if (!it) return;
    const [list, changes, ev] = await Promise.all([
      api.absences(s.id), api.deadlineChanges(it.evaluation_id), api.evaluation(it.evaluation_id)]);
    Object.assign(s, { list, changes, deadline: ev.czesc_i.termin_oceny });
  }

  function renderForm() {
    const it = item();
    if (!it) {
      replace(R.form, h("p", { class: "empty" }, "Brak pracowników z otwartym cyklem oceny."));
      return;
    }
    const today = ctx.meta.dzis;
    const od = h("input", { type: "date", id: "abs-od", required: true, value: today });
    const doo = h("input", { type: "date", id: "abs-do", required: true, value: today });
    const typ = h("select", { id: "abs-typ" },
      Object.entries(ABSENCE_LABEL).map(([v, t]) => h("option", { value: v }, t)));
    const submit = h("button", { class: "btn btn-primary", type: "submit" }, icon("check"), "Zgłoś nieobecność");

    async function onSubmit(e) {
      e.preventDefault();
      submit.disabled = true;
      try {
        s.last = await api.addAbsence(s.id, { od: od.value, do: doo.value, typ: typ.value });
        toast(s.last.zmiana_terminu ? "Zapisano nieobecność. Termin oceny został przesunięty." : "Zapisano nieobecność.");
        await load();
        renderAll();
      } catch (err) {
        const extra = err.walidacje?.length ? ` ${err.walidacje.map((w) => w.komunikat).join(" ")}` : "";
        toast(`${err.message}${extra}`, "bad");
        submit.disabled = false;
      }
    }

    replace(R.form,
      h("div", { class: "card-head" }, h("div", {},
        h("h2", {}, "Zgłoś nieobecność"),
        h("p", {}, "Wpisz okres nieobecności ocenianego. System sam sprawdzi, czy przesuwa ona termin oceny."))),
      h("form", { class: "form-grid", onsubmit: onSubmit },
        h("label", { for: "abs-od" }, "Od", od),
        h("label", { for: "abs-do" }, "Do (włącznie)", doo),
        h("label", { for: "abs-typ", class: "wide" }, "Rodzaj nieobecności", typ),
        h("div", { class: "wide row", style: { justifyContent: "space-between" } },
          h("span", { class: "small muted" }, "Termin oceny teraz: ",
            h("strong", { class: "num" }, fmtDate(s.deadline))),
          submit)),
      R.result);
    renderResult();
  }

  function renderResult() {
    const r = s.last;
    if (!r) return replace(R.result);
    const ch = r.zmiana_terminu;
    replace(R.result, h("div", { style: { padding: "0 20px 18px" } }, ch
      ? h("div", { class: "notice notice-ok", role: "status" }, icon("circleCheck"),
        h("div", {}, h("strong", {}, `Termin oceny przesunięty: ${fmtDate(ch.stary_termin)} → ${fmtDate(ch.nowy_termin)}`),
          h("div", { class: "small" }, ch.uzasadnienie)))
      : h("div", { class: "notice notice-info", role: "status" }, icon("info"),
        `Nieobecność zapisana (${r.dni} dni). Termin oceny bez zmian: ${fmtDate(r.termin_oceny)}.`)));
  }

  function renderList() {
    replace(R.list,
      h("div", { class: "card-head" }, h("div", {}, h("h2", {}, "Zgłoszone nieobecności"),
        h("p", {}, "W bieżącym cyklu oceny, od najnowszej."))),
      s.list.length
        ? h("div", { class: "table-wrap" }, h("table", { class: "data" },
          h("caption", { class: "sr-only" }, "Nieobecności ocenianego"),
          h("thead", {}, h("tr", {}, ["Okres", "Dni", "Rodzaj", "Wpływ na termin"].map((t) => h("th", { scope: "col" }, t)))),
          h("tbody", {}, s.list.map((a) => h("tr", {},
            h("td", { class: "num nowrap" }, `${fmtDate(a.od)} – ${fmtDate(a.do)}`),
            h("td", { class: "num" }, a.dni),
            h("td", {}, ABSENCE_LABEL[a.typ] || a.typ,
              a.usprawiedliwiona ? null : h("span", { class: "badge badge-bad", style: { marginLeft: "6px" } }, "nieusprawiedliwiona")),
            h("td", {}, a.zmiana_terminu
              ? h("span", { class: "badge badge-warn" }, icon("calendar"), `→ ${fmtDate(a.zmiana_terminu.nowy_termin)}`)
              : h("span", { class: "small muted" }, "bez zmiany")))))))
        : h("p", { class: "empty" }, "Brak zgłoszonych nieobecności."),
      s.changes.length ? h("div", { class: "field" },
        h("h3", { style: { marginBottom: "6px" } }, "Historia zmian terminu oceny"),
        h("ul", { class: "plain-list" }, s.changes.map((c) => h("li", {},
          h("span", {}, `${fmtDate(c.stary_termin)} → ${fmtDate(c.nowy_termin)}`),
          h("span", { class: "small muted" }, c.status === "AUTO" ? "automatycznie (nieobecność)" : c.status))))) : null);
  }

  function renderAll() {
    renderForm();
    renderList();
  }

  const picker = h("select", {
    id: "abs-person",
    onchange: (e) => { location.hash = `#/nieobecnosci/${e.target.value}`; },
  }, people.map((i) => h("option", { value: i.oceniany.id, selected: i.oceniany.id === s.id },
    `${personName(i.oceniany)} – ${STATUS_LABEL[i.status] || ""}`)));

  await load();
  const it = item();
  replace(view,
    h("div", { class: "page-head" }, h("div", {},
      h("h1", {}, "Nieobecności"),
      h("p", {}, "Usprawiedliwiona nieobecność dłuższa niż miesiąc przedłuża termin oceny o czas jej trwania."))),
    people.length ? h("div", { class: "card filters" },
      h("label", { for: "abs-person", class: "small muted row", style: { gap: "6px" } }, "Oceniany", picker),
      it ? h("span", { class: "row", style: { gap: "8px" } }, avatar(it.oceniany.imie, it.oceniany.nazwisko),
        h("a", { href: `#/ocena/${it.evaluation_id}` }, "Otwórz ocenę", icon("chevronRight"))) : null) : null,
    h("div", { class: "stack" }, R.form, R.list));
  renderAll();
}
