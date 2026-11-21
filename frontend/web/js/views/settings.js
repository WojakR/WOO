// "Ustawienia" – reminder schedule per stage (own; HR edits the office default) + my notifications.
// The server validates: hour inside office working hours, values in range; dates never fall on days off.
import { api } from "../api.js";
import { h, icon, replace, toast, fmtDate } from "../ui.js";
import { renderOfficeSections } from "./office.js";

const STAGES = [
  ["WYZNACZENIE_KRYTERIOW", "Wyznaczenie kryteriów (do 30 dni)", "np. co 7 dni: „wyznacz kryteria”"],
  ["OKRES_OCENY", "Okres oceny (12–24 miesiące)", "np. po 50 % i 75 % okresu, 2 miesiące i 2 tygodnie przed terminem"],
  ["ZAPOZNANIE", "Zapoznanie się z oceną", "np. co 3 dni, dopóki oceniany nie potwierdzi"],
];
const KINDS = [
  ["CO_DNI", "co … dni"], ["DNI_PRZED", "… dni przed terminem"], ["TYGODNIE_PRZED", "… tygodni przed terminem"],
  ["MIESIACE_PRZED", "… miesięcy przed terminem"], ["PROCENT_OKRESU", "po … % okresu"],
];

function halfHours(from, to) {
  const out = [];
  let [hh, mm] = from.split(":").map(Number);
  const [th, tm] = to.split(":").map(Number);
  while (hh * 60 + mm < th * 60 + tm) {
    out.push(`${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}`);
    mm += 30; if (mm === 60) { hh += 1; mm = 0; }
  }
  return out;
}

export async function renderSettings(view, ctx) {
  const isHr = ctx.me.rola === "KADRY";
  const s = { data: null, rules: {}, at: "11:00", notes: [] };
  const R = { office: h("div"), form: h("div"), notes: h("div") };

  async function load() {
    s.data = isHr ? await api.officeReminders() : await api.myReminders();
    s.at = s.data.godzina;
    s.rules = Object.fromEntries(STAGES.map(([k]) => [k, (s.data.etapy[k] || []).map((r) => ({ ...r }))]));
    s.notes = isHr ? [] : await api.notifications();
  }

  function stageCard([key, title, hint]) {
    const rows = s.rules[key];
    return h("div", { class: "card card-pad", style: { marginBottom: "12px" } },
      h("h3", {}, title), h("p", { class: "small muted" }, hint),
      rows.length ? rows.map((r, i) => h("div", { class: "row", style: { gap: "8px", marginBottom: "6px" } },
        h("select", { "aria-label": "Rodzaj przypomnienia", onchange: (e) => { r.rodzaj = e.target.value; } },
          KINDS.map(([v, t]) => h("option", { value: v, selected: v === r.rodzaj }, t))),
        h("input", { type: "number", min: 0, max: 730, value: r.wartosc, style: { width: "90px" },
          "aria-label": "Wartość", oninput: (e) => { r.wartosc = Number(e.target.value); } }),
        h("button", { class: "btn btn-sm btn-ghost", type: "button", "aria-label": "Usuń przypomnienie",
          onclick: () => { rows.splice(i, 1); renderForm(); } }, icon("x"), "Usuń")))
        : h("p", { class: "small muted" }, "Brak przypomnień na tym etapie."),
      h("button", { class: "btn btn-sm", type: "button",
        onclick: () => { rows.push({ rodzaj: "DNI_PRZED", wartosc: 7 }); renderForm(); } }, "+ Dodaj przypomnienie"));
  }

  function renderForm() {
    const [from, to] = s.data.godziny_pracy;
    const time = h("select", { id: "rem-time", onchange: (e) => { s.at = e.target.value; } },
      halfHours(from, to).map((t) => h("option", { value: t, selected: t === s.at }, t)));
    async function save() {
      const body = { godzina: s.at, etapy: Object.fromEntries(Object.entries(s.rules).map(([k, v]) =>
        [k, v.map((r) => ({ rodzaj: r.rodzaj, wartosc: r.wartosc }))])) };
      try {
        s.data = isHr ? await api.setOfficeReminders(body) : await api.setMyReminders(body);
        toast(isHr ? "Zapisano domyślne przypomnienia urzędu." : "Zapisano Twoje przypomnienia.");
        await load(); renderAll();
      } catch (err) {
        const extra = err.walidacje?.length ? ` ${err.walidacje.map((w) => w.komunikat).join(" ")}` : "";
        toast(`${err.message}${extra}`, "bad");
      }
    }
    async function resetOwn() {
      await api.resetMyReminders();
      toast("Przywrócono domyślne przypomnienia urzędu.");
      await load(); renderAll();
    }
    replace(R.form,
      h("div", { class: "card card-pad", style: { marginBottom: "12px" } },
        h("div", { class: "row", style: { gap: "12px", flexWrap: "wrap" } },
          h("label", { for: "rem-time" }, "Godzina przypomnień"), time,
          h("span", { class: "small muted" },
            `Tylko w dni robocze i w godzinach pracy urzędu (${from}–${to}). Termin w sobotę, niedzielę lub święto ` +
            "przesuwa się na poprzedni dzień roboczy.")),
        !isHr ? h("p", { class: "small muted", style: { marginTop: "8px" } },
          s.data.wlasne ? "Używasz własnego harmonogramu." : "Używasz domyślnego harmonogramu urzędu.") : null),
      STAGES.map(stageCard),
      h("div", { class: "row", style: { gap: "8px" } },
        h("button", { class: "btn btn-primary", type: "button", onclick: save }, icon("check"), "Zapisz"),
        !isHr && s.data.wlasne ? h("button", { class: "btn", type: "button", onclick: resetOwn },
          "Przywróć domyślne urzędu") : null));
  }

  function renderNotes() {
    if (isHr) { replace(R.notes); return; }
    replace(R.notes, h("div", { class: "card card-pad", style: { marginTop: "16px" } },
      h("h3", {}, "Moje powiadomienia"),
      s.notes.length ? h("ul", { class: "attention" }, s.notes.slice(0, 20).map((n) => h("li", {},
        h("div", { class: "row", style: { justifyContent: "space-between" } },
          h("div", {}, n.przeczytane ? n.tresc : h("strong", {}, n.tresc),
            h("div", { class: "small muted" }, fmtDate(n.zaplanowane_na.slice(0, 10)), " ", n.zaplanowane_na.slice(11, 16),
              n.evaluation_id ? [" · ", h("a", { href: `#/ocena/${n.evaluation_id}` }, "otwórz ocenę")] : null)),
          n.przeczytane ? h("span", { class: "small muted" }, "przeczytane")
            : h("button", { class: "btn btn-sm", type: "button", onclick: async () => {
              await api.readNotification(n.id); n.przeczytane = true; renderNotes(); } }, "Oznacz jako przeczytane")))))
        : h("p", { class: "empty" }, "Brak powiadomień do dziś (zegar serwera).")));
  }

  function renderAll() { renderForm(); renderNotes(); }

  await load();
  replace(view,
    h("div", { class: "page-head" }, h("div", {},
      h("h1", {}, "Ustawienia"),
      h("p", {}, isHr ? "Asystent AI, widoczność ocen, wymagania z rozporządzenia i domyślny harmonogram przypomnień urzędu."
        : "Twój asystent AI i Twoje przypomnienia na poszczególnych etapach oceny."))),
    R.office, h("h2", { style: { margin: "8px 0 10px" } }, "Przypomnienia"), R.form, R.notes);
  renderAll();
  await renderOfficeSections(R.office, ctx);
}
