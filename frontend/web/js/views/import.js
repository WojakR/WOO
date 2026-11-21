// Import of old evaluations (HR): upload a sheet, check and correct what the server read, approve.
// The server reads the form, recomputes § 11 and lists discrepancies – this view only shows and sends fields.
import { api, download } from "../api.js";
import { h, icon, replace, fmtDate, fmtNumber, toast, loading } from "../ui.js";

function errorText(err) {
  const extra = err.walidacje?.length ? ` ${err.walidacje.map((w) => w.komunikat).join(" ")}` : "";
  return `${err.message}${extra}`;
}

export async function renderImport(view, ctx, draftId = null) {
  if (ctx.me.rola !== "KADRY") {
    replace(view, h("div", { class: "card card-pad notice notice-info" }, icon("info"), "Import starych ocen jest dostępny dla działu kadr."));
    return;
  }
  const R = { list: h("div"), draft: h("div") };
  const people = (await api.employees("na_strone=200")).pozycje.map((p) => p.pracownik)
    .sort((a, b) => a.nazwisko.localeCompare(b.nazwisko, "pl"));

  const file = h("input", { type: "file", accept: ".pdf,.md,.txt", "aria-label": "Arkusz oceny (PDF lub tekst)" });
  replace(view,
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Import starych ocen"),
      h("p", {}, "Wczytaj arkusz A/B/C (PDF albo eksport tekstowy). Sprawdź odczytane pola, popraw je i zatwierdź – "
        + "ocena trafi do historii pracownika jako „zaimportowana”."))),
    h("div", { class: "card card-pad row", style: { gap: "8px", flexWrap: "wrap", marginBottom: "16px" } }, file,
      h("button", { class: "btn btn-primary", type: "button", onclick: async () => {
        if (!file.files[0]) { toast("Wybierz plik."); return; }
        try {
          const d = await api.uploadLegacyImport(file.files[0]);
          location.hash = `#/import/${d.id}`;
        } catch (err) { toast(errorText(err), "bad"); }
      } }, icon("upload"), "Wczytaj arkusz")),
    R.draft, R.list);

  async function renderList() {
    const items = await api.legacyImports();
    replace(R.list, h("section", { class: "card", style: { marginTop: "16px" } },
      h("div", { class: "card-head" }, h("h2", {}, "Wczytane arkusze")),
      items.length ? h("ul", { class: "plain-list" }, items.map((d) => h("li", {},
        h("a", { href: `#/import/${d.id}` }, `${d.pola.oceniany || d.plik} – ${d.plik}`),
        h("span", { class: `badge ${d.status === "ZATWIERDZONY" ? "badge-ok" : "badge-warn"}` },
          d.status === "ZATWIERDZONY" ? "zatwierdzony" : "do weryfikacji"))))
        : h("p", { class: "empty card-pad" }, "Nie wczytano jeszcze żadnego arkusza.")));
  }

  function renderDraft(d) {
    const p = d.pola;
    const locked = d.status !== "ROBOCZY";
    const edits = {};
    const field = (key, label, type = "text", value = p[key]) => h("label", { class: "stack", style: { gap: "4px" } },
      h("span", { class: "small" }, label),
      h("input", { type, value: value ?? "", disabled: locked, step: type === "number" ? "0.01" : null,
        oninput: (e) => { edits[key] = type === "number" ? (e.target.value === "" ? null : Number(e.target.value)) : (e.target.value || null); } }));
    const select = (key, label, options) => h("label", { class: "stack", style: { gap: "4px" } }, h("span", { class: "small" }, label),
      h("select", { disabled: locked, onchange: (e) => { edits[key] = e.target.value || null; } },
        h("option", { value: "" }, "–"), options.map(([v, t]) => h("option", { value: v, selected: String(p[key] ?? "") === String(v) }, t))));
    const scores = {};
    const blocking = d.rozbieznosci.filter((x) => x.waga === "BLAD");
    async function save() {
      const body = { ...edits };
      if (Object.keys(scores).length) body.punkty = scores;
      try {
        renderDraft(await api.fixLegacyImport(d.id, body));
        toast("Zapisano poprawki – sprawdzono ponownie.");
      } catch (err) { toast(errorText(err), "bad"); }
    }
    async function approve(accept) {
      try {
        const done = await api.approveLegacyImport(d.id, { akceptuje_rozbieznosci: accept });
        toast("Zatwierdzono – ocena jest w historii pracownika.");
        renderDraft(done); renderList();
      } catch (err) { toast(errorText(err), "bad"); }
    }
    replace(R.draft, h("section", { class: "card card-pad stack", "aria-labelledby": "imp-h" },
      h("div", { class: "row", style: { justifyContent: "space-between", flexWrap: "wrap", gap: "8px" } },
        h("h2", { id: "imp-h" }, `Weryfikacja: ${d.plik}`),
        h("button", { class: "btn btn-sm", type: "button", onclick: () => download(`/legacy-import/${d.id}/file`, d.plik)
          .catch((err) => toast(errorText(err), "bad")) }, icon("download"), "Oryginał")),
      d.evaluation_id ? h("p", { class: "notice notice-ok" }, icon("check"), "Zaimportowano – ",
        h("a", { href: `#/ocena/${d.evaluation_id}` }, "otwórz ocenę")) : null,
      d.rozbieznosci.length ? h("ul", { class: "stack", style: { gap: "6px", listStyle: "none", padding: 0 } }, d.rozbieznosci.map((x) =>
        h("li", { class: `notice ${x.waga === "BLAD" ? "notice-bad" : "notice-info"}` }, icon(x.waga === "BLAD" ? "alert" : "info"), x.komunikat)))
        : h("p", { class: "notice notice-ok" }, icon("check"), "Brak rozbieżności – średnia, poziom i wynik są zgodne z § 11."),
      d.uwagi.length ? h("ul", { class: "small muted" }, d.uwagi.map((u) => h("li", {}, u))) : null,
      h("div", { class: "grid-2" },
        h("div", { class: "stack" },
          select("pracownik_id", `Pracownik (w arkuszu: ${p.oceniany || "?"})`, people.map((x) => [x.id, `${x.imie} ${x.nazwisko}`])),
          select("arkusz", "Arkusz", [["A", "A"], ["B", "B"], ["C", "C"]]),
          field("data_rozmowy", "Data rozmowy oceniającej", "date"),
          field("okres_od", "Okres oceny od", "date"), field("okres_do", "Okres oceny do", "date"),
          field("data_sporzadzenia", "Data sporządzenia oceny", "date"), field("data_zapoznania", "Data zapoznania", "date")),
        h("div", { class: "stack" },
          field("srednia", "Średnia w arkuszu", "number"),
          select("poziom", "Poziom", d.poziomy.map((x) => [x, x])),
          select("wynik", "Wynik", [["pozytywna", "pozytywna"], ["negatywna", "negatywna"]]),
          d.wyliczone ? h("p", { class: "small muted" }, `Z ocen cząstkowych: średnia ${fmtNumber(d.wyliczone.srednia)}, `
            + `${d.wyliczone.poziom}, ${d.wyliczone.wynik}.`) : h("p", { class: "small muted" }, "Nie wszystkie oceny cząstkowe są znane."),
          h("table", { class: "data compact" }, h("thead", {}, h("tr", {}, h("th", {}, "Kryterium"), h("th", {}, "Ocena cząstkowa"))),
            h("tbody", {}, d.kryteria.map((k) => h("tr", {}, h("td", {}, k.nazwa), h("td", {},
              h("select", { disabled: locked, "aria-label": `Ocena: ${k.nazwa}`, onchange: (e) => { scores[k.kod] = e.target.value ? Number(e.target.value) : null; } },
                h("option", { value: "" }, "nie odczytano"), [1, 3, 5, 7, 9].map((v) => h("option", { value: v, selected: k.punkty === v }, v)))))))))),
      locked ? null : h("div", { class: "row", style: { gap: "8px", flexWrap: "wrap", justifyContent: "flex-end" } },
        h("button", { class: "btn", type: "button", onclick: save }, icon("save"), "Zapisz poprawki"),
        blocking.length && blocking.every((x) => !x.kod.startsWith("BRAK_"))
          ? h("button", { class: "btn", type: "button", onclick: () => approve(true) }, "Zatwierdź mimo rozbieżności") : null,
        h("button", { class: "btn btn-primary", type: "button", disabled: blocking.length > 0, onclick: () => approve(false) },
          icon("check"), "Zatwierdź import")),
      h("p", { class: "small muted" }, `Wczytano ${fmtDate(d.przeslano)}.`)));
  }

  await renderList();
  if (draftId) {
    replace(R.draft, loading());
    renderDraft(await api.legacyImport(draftId));
  }
}
