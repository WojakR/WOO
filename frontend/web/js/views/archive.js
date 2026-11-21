// Archive of closed evaluations (HR / administrator): frozen sheets with checksums, the retention review and
// the e-Akt retry. The server decides what is closed, what is past retention and what may be deleted
// (app/application/archive.py); this view only shows it and sends the administrator's explicit approval.
import { api, download } from "../api.js";
import { h, icon, replace, fmtDate, toast, loading } from "../ui.js";

const KIND = { AKTA: "Arkusz w aktach osobowych", NOTATKI: "Notatki robocze przełożonego" };

function errorText(err) {
  const extra = err.walidacje?.length ? ` ${err.walidacje.map((w) => w.komunikat ?? w).join(" ")}` : "";
  return `${err.message}${extra}`;
}

export async function renderArchive(view, ctx) {
  if (ctx.me.rola !== "KADRY") {
    replace(view, h("div", { class: "card card-pad notice notice-info" }, icon("info"), "Archiwum ocen obsługuje dział kadr."));
    return;
  }
  const R = { review: h("div"), list: h("div") };
  const confirming = new Set();  // review items waiting for the second click ("Potwierdź usunięcie")

  async function runArchive(btn) {
    btn.disabled = true;
    try {
      const r = await api.archiveRun();
      toast(r.zamrozono.length ? `Zarchiwizowano ${r.zamrozono.length} ocen.` : "Brak nowych zakończonych ocen do archiwizacji.");
      await load();
    } catch (err) { toast(errorText(err), "bad"); } finally { btn.disabled = false; }
  }

  async function retryEakt(btn) {
    btn.disabled = true;
    try {
      const r = await api.eaktRetry();
      if (r.tryb === "off") toast("Eksport do e-Akt jest wyłączony (EAKT_MODE=off).");
      else if (!r.ponowiono.length) toast("Brak nieudanych eksportów do ponowienia.");
      else {
        const ok = r.ponowiono.filter((x) => x.status === "WYSLANO").length;
        toast(`Ponowiono ${r.ponowiono.length} eksportów, udane: ${ok}.`, ok === r.ponowiono.length ? "" : "bad");
      }
    } catch (err) { toast(errorText(err), "bad"); } finally { btn.disabled = false; }
  }

  async function remove(item) {
    const key = `${item.rodzaj}:${item.id ?? item.evaluation_id}`;
    if (!confirming.has(key)) { confirming.add(key); renderReview(lastReview); return; }
    try {
      if (item.rodzaj === "AKTA") await api.archiveDelete(item.id);
      else {
        const r = await api.archiveDeleteNotes(item.evaluation_id);
        toast(`Usunięto notatek: ${r.usunieto_notatek}.`);
      }
      if (item.rodzaj === "AKTA") toast("Usunięto rekord archiwum.");
      confirming.delete(key);
      await load();
    } catch (err) { toast(errorText(err), "bad"); }
  }

  let lastReview = [];
  function renderReview(items) {
    lastReview = items;
    replace(R.review, h("section", { class: "card", "aria-labelledby": "arch-rev-h" },
      h("div", { class: "card-head" }, h("div", {}, h("h2", { id: "arch-rev-h" }, "Po okresie przechowywania"),
        h("p", {}, "System niczego nie usuwa sam. Każde usunięcie zatwierdza administrator."))),
      items.length ? h("div", { class: "table-wrap" }, h("table", { class: "data rules" },
        h("thead", {}, h("tr", {}, ["Rodzaj", "Pracownik", "Przechowywać do", "Podstawa", ""].map((c) => h("th", { scope: "col" }, c)))),
        h("tbody", {}, items.map((i) => {
          const key = `${i.rodzaj}:${i.id ?? i.evaluation_id}`;
          const sure = confirming.has(key);
          return h("tr", {},
            h("td", {}, KIND[i.rodzaj] || i.rodzaj),
            h("td", {}, i.evaluation_id ? h("a", { href: `#/ocena/${i.evaluation_id}` }, i.pracownik) : i.pracownik),
            h("td", { class: "nowrap" }, fmtDate(i.termin_przechowywania)),
            h("td", { class: "small" }, i.powod),
            h("td", { class: "nowrap" },
              sure ? h("button", { class: "btn btn-sm", type: "button", onclick: () => { confirming.delete(key); renderReview(lastReview); } }, "Anuluj") : null,
              h("button", { class: `btn btn-sm${sure ? " btn-danger" : ""}`, type: "button", onclick: () => remove(i) },
                sure ? "Potwierdź usunięcie" : "Usuń…")));
        }))))
        : h("p", { class: "empty card-pad" }, "Nic nie przekroczyło okresu przechowywania.")));
  }

  function renderList(records) {
    replace(R.list, h("section", { class: "card", "aria-labelledby": "arch-list-h" },
      h("div", { class: "card-head" }, h("div", {}, h("h2", { id: "arch-list-h" }, "Zarchiwizowane oceny"),
        h("p", {}, "Zamrożony arkusz (PDF) i dane oceny z sumami kontrolnymi SHA-256 – zmiana po archiwizacji jest wykrywana."))),
      records.length ? h("div", { class: "table-wrap" }, h("table", { class: "data rules" },
        h("thead", {}, h("tr", {}, ["Pracownik", "Zarchiwizowano", "SHA-256 (PDF)", "Integralność", ""].map((c) => h("th", { scope: "col" }, c)))),
        h("tbody", {}, records.map((r) => h("tr", {},
          h("td", {}, h("a", { href: `#/ocena/${r.evaluation_id}` }, r.pracownik)),
          h("td", { class: "nowrap" }, fmtDate(r.zamrozono)),
          h("td", {}, h("code", { title: r.sha256_pdf }, `${r.sha256_pdf.slice(0, 12)}…`)),
          h("td", {}, r.zgodny ? h("span", { class: "badge badge-ok" }, icon("check"), "zgodny")
            : h("span", { class: "badge badge-bad" }, icon("alert"), "naruszony")),
          h("td", {}, h("button", { class: "btn btn-sm", type: "button",
            onclick: () => download(`/archive/${r.id}/pdf`, `archiwum-ocena-${r.evaluation_id}.pdf`).catch((err) => toast(errorText(err), "bad")) },
          icon("download"), "PDF")))))))
        : h("p", { class: "empty card-pad" }, "Archiwum jest puste. Zakończone oceny trafiają tu po upływie terminu na sprzeciw.")));
  }

  async function load() {
    const [records, review] = await Promise.all([api.archive(), api.archiveReview()]);
    renderList(records);
    renderReview(review);
  }

  const runBtn = h("button", { class: "btn btn-primary", type: "button", onclick: (e) => runArchive(e.currentTarget) },
    icon("archive"), "Archiwizuj zakończone oceny");
  const eaktBtn = h("button", { class: "btn", type: "button", onclick: (e) => retryEakt(e.currentTarget) },
    icon("reset"), "Ponów nieudane eksporty do e-Akt");
  replace(view,
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Archiwum ocen"),
      h("p", {}, "Arkusz oceny jest częścią akt osobowych (część B). Okresy przechowywania ustawia urząd w config/ustawienia_urzedu.json."))),
    h("div", { class: "row", style: { gap: "8px", flexWrap: "wrap", marginBottom: "16px" } }, runBtn, eaktBtn),
    h("div", { class: "stack" }, R.review, R.list));
  replace(R.list, loading());
  await load();
}
