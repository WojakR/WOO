// Settings sections shown above the reminder schedule:
// - "Asystent AI" – the off switch of the AI assistant and the virtual HR partner (own; HR: office-wide),
// - "Widoczność ocen" – whole subtree or direct reports only (HR edits),
// - "Wymagania z rozporządzenia" – what the system enforces; HR changes the terms after an amendment.
// Every rule and every check stays on the server; this page only shows and sends values.
import { api } from "../api.js";
import { h, icon, replace, toast, fmtDate } from "../ui.js";
import { ctx as appCtx, renderTopbar } from "../main.js";

function switchRow(id, label, hint, checked, disabled, onchange) {
  return h("div", { class: "row", style: { gap: "10px", alignItems: "flex-start", marginBottom: "10px" } },
    h("input", { type: "checkbox", id, checked, disabled, onchange: (e) => onchange(e.target.checked),
      style: { width: "18px", height: "18px", marginTop: "2px" } }),
    h("label", { for: id }, h("strong", {}, label), h("div", { class: "small muted" }, hint)));
}

function errorText(err) {
  const extra = err.walidacje?.length ? ` ${err.walidacje.map((w) => w.komunikat).join(" ")}` : "";
  return `${err.message}${extra}`;
}

export async function renderOfficeSections(box, ctx) {
  const isHr = ctx.me.rola === "KADRY";
  const s = { office: null, mine: null, rules: null, edits: {}, basis: "" };
  const R = { ai: h("div"), vis: h("div"), rules: h("div") };

  async function refreshMeta() {
    appCtx.meta = await api.meta();
    ctx.meta = appCtx.meta;
    renderTopbar();
  }

  // ------------------------------------------------------------ AI switch
  function renderAi() {
    const o = s.office;
    const serverOff = o.tryb_ai_serwera === "OFF";
    const note = serverOff
      ? h("p", { class: "small muted" }, icon("info"), " Serwer nie ma skonfigurowanego modelu (AI_MODE=off) – " +
        "asystent działa na szablonach i regułach niezależnie od przełącznika.")
      : null;
    if (isHr) {
      const set = (field) => async (value) => {
        try {
          s.office = await api.setOffice({ [field]: value });
          toast(value ? "Włączono dla całego urzędu." : "Wyłączono dla całego urzędu.");
          await refreshMeta(); renderAi();
        } catch (err) { toast(errorText(err), "bad"); renderAi(); }
      };
      replace(R.ai, h("div", { class: "card card-pad", style: { marginBottom: "12px" } },
        h("h3", {}, "Asystent AI w urzędzie"),
        h("p", { class: "small muted", style: { marginBottom: "10px" } },
          "Wyłączenie dotyczy wszystkich pracowników. Bez AI każda funkcja działa w wersji bez modelu językowego " +
          "(szablony i reguły) – proces oceny przebiega tak samo."),
        switchRow("office-ai", "Asystent AI (model językowy)",
          "Podpowiedzi kryteriów, klasyfikacja notatek, szkice uzasadnień i notatki na rozmowę.",
          o.asystent_ai, false, set("asystent_ai")),
        switchRow("office-hr", "Wirtualny HR partner",
          "Sygnały dla przełożonego (przeciążenie, długa nieobecność, zmiana obowiązków).",
          o.hr_partner, false, set("hr_partner")),
        note));
      return;
    }
    const m = s.mine;
    const set = (field) => async (value) => {
      try {
        s.mine = await api.setMyAssistant({ [field]: value });
        toast(value ? "Włączono." : "Wyłączono – tylko dla Ciebie.");
        await refreshMeta(); renderAi();
      } catch (err) { toast(errorText(err), "bad"); renderAi(); }
    };
    const officeOff = (on) => (on ? "" : " Wyłączone przez administratora dla całego urzędu.");
    replace(R.ai, h("div", { class: "card card-pad", style: { marginBottom: "12px" } },
      h("h3", {}, "Mój asystent AI"),
      h("p", { class: "small muted", style: { marginBottom: "10px" } },
        "Możesz pracować bez AI – wszystkie funkcje działają wtedy na szablonach i regułach."),
      switchRow("my-ai", "Asystent AI (model językowy)",
        `Podpowiedzi, szkice i notatki z użyciem modelu.${officeOff(m.asystent_ai_w_urzedzie)}`,
        m.asystent_ai && m.asystent_ai_w_urzedzie, !m.asystent_ai_w_urzedzie, set("asystent_ai")),
      switchRow("my-hr", "Wirtualny HR partner", `Panel podpowiedzi w arkuszu oceny.${officeOff(m.hr_partner_w_urzedzie)}`,
        m.hr_partner && m.hr_partner_w_urzedzie, !m.hr_partner_w_urzedzie, set("hr_partner")),
      note));
  }

  // ------------------------------------------------------------ visibility
  function renderVisibility() {
    const o = s.office;
    const options = [
      ["PODDRZEWO", "Całe poddrzewo", "Przełożony widzi (do odczytu) oceny swoich podwładnych i ich podwładnych."],
      ["BEZPOSREDNI", "Tylko bezpośredni podwładni", "Przełożony widzi wyłącznie osoby, które sam ocenia."],
    ];
    const current = options.find(([v]) => v === o.zakres_widocznosci);
    replace(R.vis, h("div", { class: "card card-pad", style: { marginBottom: "12px" } },
      h("h3", {}, "Widoczność ocen"),
      h("p", { class: "small muted", style: { marginBottom: "10px" } },
        "Wypełniać ocenę może zawsze tylko bezpośredni oceniający albo jego zastępca. Ustawienie dotyczy wglądu."),
      isHr
        ? options.map(([value, label, hint]) => h("div", { class: "row", style: { gap: "10px", marginBottom: "8px", alignItems: "flex-start" } },
          h("input", { type: "radio", name: "scope", id: `scope-${value}`, value, checked: value === o.zakres_widocznosci,
            style: { marginTop: "3px" },
            onchange: async () => {
              try {
                s.office = await api.setOffice({ zakres_widocznosci: value });
                toast(`Widoczność: ${label.toLowerCase()}.`);
              } catch (err) { toast(errorText(err), "bad"); }
              renderVisibility();
            } }),
          h("label", { for: `scope-${value}` }, h("strong", {}, label), h("div", { class: "small muted" }, hint))))
        : h("p", {}, h("strong", {}, current?.[1] || o.zakres_widocznosci), " – ", current?.[2] || "",
          h("span", { class: "small muted" }, " Zmienia administrator."))));
  }

  // ------------------------------------------------------------ requirements of the regulation
  function renderRules() {
    const r = s.rules;
    const rows = r.parametry.map((p) => {
      const value = s.edits[p.klucz] ?? p.wartosc;
      const changed = p.wartosc !== p.domyslna;
      return h("tr", {},
        h("td", {}, p.nazwa, h("div", { class: "small muted" }, p.podstawa)),
        h("td", { class: "num" }, isHr
          ? h("input", { type: "number", min: p.min, max: p.max, value, style: { width: "80px" },
            "aria-label": `${p.nazwa} (${p.jednostka})`,
            oninput: (e) => { s.edits[p.klucz] = Number(e.target.value); } })
          : h("strong", {}, String(p.wartosc)), " ", p.jednostka),
        h("td", { class: "small muted" }, changed ? `w rozporządzeniu: ${p.domyslna}` : "zgodnie z rozporządzeniem"));
    });

    async function save() {
      const wartosci = Object.fromEntries(Object.entries(s.edits)
        .filter(([k, v]) => r.parametry.find((p) => p.klucz === k)?.wartosc !== v));
      if (!Object.keys(wartosci).length) { toast("Brak zmian do zapisania."); return; }
      try {
        s.rules = await api.setRules({ wartosci, podstawa_zmiany: s.basis });
        s.edits = {}; s.basis = "";
        toast("Zapisano. Terminy wszystkich ocen są liczone według nowych wartości.");
        await refreshMeta(); renderRules();
      } catch (err) { toast(errorText(err), "bad"); }
    }
    async function reset() {
      try {
        s.rules = await api.resetRules();
        s.edits = {};
        toast("Przywrócono wartości z rozporządzenia.");
        await refreshMeta(); renderRules();
      } catch (err) { toast(errorText(err), "bad"); }
    }

    replace(R.rules, h("div", { class: "card card-pad", style: { marginBottom: "12px" } },
      h("div", { class: "row", style: { justifyContent: "space-between", flexWrap: "wrap", gap: "8px" } },
        h("h3", {}, "Wymagania z rozporządzenia"),
        r.zmienione ? h("span", { class: "badge badge-warn" }, icon("alert"), "zmienione przez administratora")
          : h("span", { class: "badge badge-ok" }, icon("check"), "zgodne z rozporządzeniem")),
      h("p", { class: "small muted", style: { margin: "6px 0 10px" } },
        "Rozporządzenie Prezesa Rady Ministrów z 4.04.2016 r. (Dz. U. poz. 470) i ustawa o służbie cywilnej. " +
        (isHr ? "Po nowelizacji zmień wartości i podaj podstawę – system przeliczy terminy." : "Zmienia administrator po nowelizacji.")),
      h("div", { class: "table-wrap" }, h("table", { class: "data rules" },
        h("thead", {}, h("tr", {}, h("th", {}, "Termin / wymaganie"), h("th", {}, "Wartość"), h("th", {}, ""))),
        h("tbody", {}, rows))),
      isHr ? h("div", { class: "row", style: { gap: "8px", marginTop: "12px", flexWrap: "wrap" } },
        h("input", { type: "text", placeholder: "Podstawa zmiany, np. nowelizacja, Dz. U. 2027 poz. 123",
          "aria-label": "Podstawa zmiany", value: s.basis, style: { flex: "1 1 320px" },
          oninput: (e) => { s.basis = e.target.value; } }),
        h("button", { class: "btn btn-primary", type: "button", onclick: save }, icon("check"), "Zapisz zmiany"),
        r.zmienione ? h("button", { class: "btn", type: "button", onclick: reset }, "Przywróć z rozporządzenia") : null) : null,
      h("details", { style: { marginTop: "14px" } },
        h("summary", {}, "Pozostałe wymagania (skala, poziomy, kryteria obowiązkowe)"),
        h("dl", { class: "stack", style: { gap: "8px", marginTop: "8px" } }, r.wymagania.map((w) => h("div", {},
          h("dt", {}, h("strong", {}, w.tytul), h("span", { class: "small muted" }, ` · ${w.podstawa}`)),
          h("dd", { class: "small", style: { margin: 0 } }, w.tresc))))),
      r.zmiany.length ? h("details", { style: { marginTop: "10px" } },
        h("summary", {}, `Historia zmian (${r.zmiany.length})`),
        h("ul", { class: "plain-list" }, r.zmiany.map((z) => h("li", {},
          h("span", {}, `${fmtDate(z.kiedy)} · ${z.nazwa}: ${z.stara} → ${z.nowa}`),
          h("span", { class: "small muted" }, `${z.podstawa_zmiany} (${z.kto})`))))) : null));
  }

  [s.office, s.rules, s.mine] = await Promise.all([api.office(), api.rules(), isHr ? null : api.myAssistant()]);
  replace(box, R.ai, R.vis, R.rules);
  renderAi(); renderVisibility(); renderRules();
}
