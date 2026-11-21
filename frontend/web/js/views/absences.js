// UC8 – "Nieobecności": register an absence of the evaluated person. Whether and how far the evaluation
// deadline moves is decided by the server (art. 81 ust. 7); this screen only shows what it returns.
// Also: change of the deadline by the evaluator (art. 81 ust. 8, letter to the evaluated person – § 8),
// the evaluator's own planned absence (who needs a deputy or a new deadline) and HR's inbox of requests.
import { api } from "../api.js";
import { h, icon, replace, fmtDate, avatar, toast } from "../ui.js";
import { ABSENCE_LABEL, STATUS_LABEL, personName } from "../labels.js";

export async function renderAbsences(view, ctx, employeeId) {
  const data = await api.dashboard();
  const people = data.pozycje.filter((i) => i.evaluation_id && i.status !== "ZAKONCZONA");
  const s = { id: employeeId || people[0]?.oceniany.id || null, list: [], changes: [], last: null, deadline: null };
  const item = () => people.find((i) => i.oceniany.id === s.id);

  const R = { list: h("div", { class: "card" }), form: h("div", { class: "card" }), result: h("div"),
    change: h("div"), mine: h("div"), inbox: h("div") };
  const isHr = ctx.me.rola === "KADRY";
  const REASONS = {
    PRZEWIDYWANA_NIEOBECNOSC_OCENIANEGO: "przewidywana dłuższa nieobecność ocenianego (pkt 2)",
    PRZEWIDYWANA_NIEOBECNOSC_OCENIAJACEGO: "przewidywana dłuższa nieobecność oceniającego (pkt 3)",
    WNIOSEK_OCENIANEGO: "wniosek ocenianego (pkt 4)",
    ZMIANA_OCENIAJACEGO: "zmiana na stanowisku oceniającego (pkt 1)",
  };
  const STATUS_TXT = { ZLOZONY: "czeka na decyzję kadr", ZAAKCEPTOWANY: "zmieniony", ODRZUCONY: "odrzucony", AUTO: "automatycznie (nieobecność)" };
  const errText = (err) => `${err.message}${err.walidacje?.length ? ` ${err.walidacje.map((w) => w.komunikat).join(" ")}` : ""}`;

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
          h("span", { class: "small muted" }, STATUS_TXT[c.status] || c.status),
          c.pismo_pdf ? h("a", { class: "btn btn-sm", href: `/api/deadline-changes/${c.id}/pdf`, target: "_blank", rel: "noopener" },
            "Pismo do ocenianego (PDF)") : null)))) : null);
  }

  // ---- art. 81 ust. 8: the evaluator changes the deadline
  function renderChange() {
    const it = item();
    if (!it || !ctx.me.czy_oceniajacy || ["OCENA_DO_ZAPOZNANIA", "ZAKONCZONA", "SPRZECIW"].includes(it.status)) {
      replace(R.change);
      return;
    }
    const reason = h("select", { id: "dc-reason" }, Object.entries(REASONS).map(([v, t]) => h("option", { value: v }, t)));
    const date = h("input", { type: "date", id: "dc-date", required: true });
    const text = h("textarea", { id: "dc-text", rows: 3, required: true,
      placeholder: "Uzasadnienie – trafi do pisma do ocenianego" });
    const go = h("button", { class: "btn btn-primary", type: "submit" }, icon("calendar"), "Zmień termin");
    replace(R.change, h("section", { class: "card" },
      h("div", { class: "card-head" }, h("div", {}, h("h2", {}, "Zmiana terminu oceny"),
        h("p", {}, "Art. 81 ust. 8 ustawy: decyduje oceniający, gdy od ostatniej oceny minęło ponad 6 miesięcy. Oceniany dostaje pismo."))),
      h("form", { class: "form-grid", onsubmit: async (e) => {
        e.preventDefault();
        go.disabled = true;
        try {
          const r = await api.requestDeadlineChange(it.evaluation_id, { powod: reason.value, nowy_termin: date.value, uzasadnienie: text.value });
          toast(r.status === "ZLOZONY" ? "Wniosek przekazano do działu kadr." : `Termin oceny zmieniony na ${fmtDate(r.nowy_termin)}.`);
          await load(); renderAll();
        } catch (err) {
          toast(errText(err), "bad");
          go.disabled = false;
        }
      } },
      h("label", { for: "dc-reason", class: "wide" }, "Podstawa (art. 81 ust. 8)", reason),
      h("label", { for: "dc-date" }, "Nowy termin oceny", date),
      h("label", { for: "dc-text", class: "wide" }, "Uzasadnienie", text),
      h("div", { class: "wide row", style: { justifyContent: "flex-end" } }, go))));
  }

  // ---- the evaluator's own planned absence
  function renderMine() {
    if (!ctx.me.czy_oceniajacy) { replace(R.mine); return; }
    const od = h("input", { type: "date", id: "ea-od", required: true });
    const doo = h("input", { type: "date", id: "ea-do", required: true });
    const out = h("div");
    replace(R.mine, h("section", { class: "card" },
      h("div", { class: "card-head" }, h("div", {}, h("h2", {}, "Moja planowana nieobecność"),
        h("p", {}, "Sprawdź, czyje terminy wypadają w tym czasie – wyznacz zastępcę albo zmień termin oceny."))),
      h("form", { class: "form-grid", onsubmit: async (e) => {
        e.preventDefault();
        try {
          const r = await api.evaluatorAbsence({ oceniajacy_id: ctx.me.pracownik.id, od: od.value, do: doo.value });
          replace(out, h("div", { style: { padding: "0 20px 18px" } },
            h("p", { class: "notice notice-info" }, icon("info"), r.komunikat),
            r.podpowiedzi.length ? h("ul", { class: "plain-list" }, r.podpowiedzi.map((p) => h("li", {},
              h("span", {}, `${personName(p.oceniany)} – ${p.rodzaj_terminu === "KRYTERIA" ? "kryteria do" : "ocena do"} ${fmtDate(p.termin)}`),
              p.zastepca ? h("span", { class: "small muted" }, `zastępca: ${personName(p.zastepca)}`)
                : p.mozna_zmienic_termin ? h("a", { class: "btn btn-sm", href: `#/nieobecnosci/${p.oceniany.id}` },
                  `Zmień termin (propozycja: ${fmtDate(p.proponowany_termin)})`)
                  : h("span", { class: "small muted" }, p.dlaczego_nie.join(" ") || "wyznacz zastępcę")))) : null));
        } catch (err) { toast(errText(err), "bad"); }
      } },
      h("label", { for: "ea-od" }, "Od", od),
      h("label", { for: "ea-do" }, "Do (włącznie)", doo),
      h("div", { class: "wide row", style: { justifyContent: "flex-end" } },
        h("button", { class: "btn", type: "submit" }, "Sprawdź terminy"))),
      out));
  }

  // ---- HR: requests waiting for a decision (office setting zmiana_terminu.zatwierdza = KADRY)
  async function renderInbox() {
    if (!isHr) { replace(R.inbox); return; }
    const waiting = await api.allDeadlineChanges("ZLOZONY");
    if (!waiting.length) { replace(R.inbox); return; }
    const decide = (c, status) => async () => {
      try {
        await api.decideDeadlineChange(c.id, { status });
        toast(status === "ZAAKCEPTOWANY" ? "Zaakceptowano – termin zmieniony, pismo gotowe." : "Odrzucono wniosek.");
        await load(); renderAll();
      } catch (err) { toast(errText(err), "bad"); }
    };
    replace(R.inbox, h("section", { class: "card" },
      h("div", { class: "card-head" }, h("div", {}, h("h2", {}, "Wnioski o zmianę terminu"), h("p", {}, `Czeka na decyzję: ${waiting.length}`))),
      h("ul", { class: "plain-list", style: { padding: "0 20px 18px" } }, waiting.map((c) => h("li", {},
        h("div", {}, h("strong", {}, personName(c.oceniany)), ` ${fmtDate(c.stary_termin)} → ${fmtDate(c.nowy_termin)}`,
          h("div", { class: "small muted" }, `${REASONS[c.powod] || c.powod}. ${c.uzasadnienie || ""}`)),
        h("div", { class: "row" },
          h("button", { class: "btn btn-sm btn-primary", type: "button", onclick: decide(c, "ZAAKCEPTOWANY") }, "Akceptuj"),
          h("button", { class: "btn btn-sm", type: "button", onclick: decide(c, "ODRZUCONY") }, "Odrzuć")))))));
  }

  function renderAll() {
    renderForm();
    renderList();
    renderChange();
    renderMine();
    renderInbox();
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
    h("div", { class: "stack" }, R.inbox, R.form, R.list, R.change, R.mine));
  renderAll();
}
