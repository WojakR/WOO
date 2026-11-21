// Screen 1 – one evaluation (evaluator's view; the evaluated person sees the same sheet read-only with their own actions).
// Every rule (average, level, outcome, locks, allowed actions, validations) comes from the server.
import { api, ApiError, currentUserId } from "../api.js";
import { h, icon, replace, fmtDate, fmtNumber, avatar, daysBetween, daysLeftText, urgency, toast, loading, helpLink } from "../ui.js";
import {
  STAGES, stageIndex, STATUS_LABEL, LEVEL_LABEL, SCALE_SHORT, ACTION_LABEL, ACTION_DONE, EMPLOYMENT_LABEL, SIGNAL_LABEL, personName,
} from "../labels.js";

const BLOCK_HINT = {
  UZASADNIENIE_WYMAGANE: "Uzupełnij uzasadnienie oceny",
  IPRZ_WYMAGANE: "Uzupełnij wnioski do IPRZ",
  BRAK_OCENY: "Oceń wszystkie kryteria",
};
const CHECK_LABEL = {
  UZASADNIENIE_WYMAGANE: "Uzasadnienie oceny",
  IPRZ_WYMAGANE: "Wnioski do indywidualnego programu rozwoju zawodowego",
};
const TEXT_FIELDS = {
  uzasadnienie: { label: "Uzasadnienie oceny", draft: "UZASADNIENIE",
    help: ["rozporzadzenie-oceny-okresowe-2016", "Oceniający sporządza uzasadnienie", "§ 11 ust. 3–4 – uzasadnienie oceny"] },
  wnioski_iprz: { label: "Wnioski do indywidualnego programu rozwoju zawodowego", draft: "IPRZ",
    help: ["ustawa-sc-wyciag-oceny", "rozwoju zawodowego", "art. 81 ust. 5 – wnioski do IPRZ"] },
};

export async function renderEvaluation(view, id, ctx) {
  const s = {
    ev: await api.evaluation(id),
    evidence: null, notes: [], hr: null, hrError: null, criteriaDict: null,
    drafts: {}, open: new Set(), text: {}, dirty: new Set(), confirming: false, busy: false,
  };
  const meId = ctx.me.pracownik.id;
  // the server decides (evaluator or their active deputy – app/domain/access.py); ID check is the fallback
  const isEvaluator = () => s.ev.jako_oceniajacy ?? s.ev.oceniajacy.id === meId;
  const canSeeWorkNotes = () => isEvaluator() || ctx.me.rola === "KADRY";
  const editable = (f) => s.ev.edytowalne_pola.includes(f);
  const aiOn = () => Boolean(ctx.meta.funkcje_ai?.szkic_uzasadnienia) && isEvaluator();
  const blocking = () => s.ev.walidacje.filter((w) => w.waga === "BLAD");
  const syncText = () => {
    for (const f of Object.keys(TEXT_FIELDS)) if (!s.dirty.has(f)) s.text[f] = s.ev.czesc_ii[f] || "";
  };
  syncText();

  // Regions re-rendered independently, so a click never lands on a node that was just replaced.
  const R = {
    head: h("div"), stepper: h("div"), person: h("div"), main: h("div", { class: "stack" }),
    aside: h("div", { class: "aside" }), actions: h("div"),
  };

  async function loadSide() {
    const tasks = [];
    if (canSeeWorkNotes()) {  // evaluator, deputy, HR – the evaluated person and managers above get 403 anyway
      tasks.push(api.evidence(id).then((x) => { s.evidence = x; }).catch(() => {}));
      tasks.push(api.notes(id).then((x) => { s.notes = x; }).catch(() => {}));
    }
    if (s.ev.status === "ROZMOWA_OCENIAJACA" && isEvaluator()) {
      tasks.push(Promise.all([api.wellbeingChecklist(), api.wellbeing(id)])
        .then(([list, answers]) => { s.wb = { list, answers, draft: { ...answers.odpowiedzi } }; }).catch(() => {}));
    }
    if (s.ev.status === "KRYTERIA_DO_WYZNACZENIA" && !s.criteriaDict) {
      tasks.push(api.criteria(s.ev.arkusz).then((x) => { s.criteriaDict = x; }));
    }
    await Promise.all(tasks);
  }

  async function loadHr() {
    if (!isEvaluator() || !ctx.meta.funkcje_ai?.hr_partner) return;
    if (["OCENA_DO_ZAPOZNANIA", "ZAKONCZONA"].includes(s.ev.status)) return;
    try {
      s.hr = await api.hrPartner(id);
    } catch (e) {
      s.hrError = e.message;
    }
    renderAside();
  }

  async function refreshEvaluation() {
    s.ev = await api.evaluation(id);
    syncText();
  }

  // ------------------------------------------------------------ header + stepper + person
  function renderHead() {
    const ev = s.ev;
    const done = ["OCENA_DO_ZAPOZNANIA", "ZAKONCZONA", "SPRZECIW"].includes(ev.status);
    const criteriaStage = ["KRYTERIA_DO_WYZNACZENIA", "KRYTERIA_DO_POTWIERDZENIA"].includes(ev.status);
    const due = criteriaStage ? ev.czesc_i.termin_wyznaczenia_kryteriow : ev.czesc_i.termin_oceny;
    const days = daysBetween(ctx.meta.dzis, due);
    const u = urgency(days);
    const cls = u === "PO_TERMINIE" ? "badge-bad" : u === "OK" ? "badge-idle" : "badge-warn";
    replace(R.head,
      h("a", { class: "back", href: "#/" }, icon("arrowLeft"), "Moje oceny"),
      h("div", { class: "eval-head" },
        h("div", { class: "title" },
          h("h1", {}, `Ocena okresowa – ${personName(ev.oceniany)}`),
          h("span", { class: "badge badge-sheet" }, `Arkusz ${ev.arkusz}`),
          ev.status === "ZAKONCZONA" ? h("span", { class: "badge badge-ok" }, icon("check"), "Zakończona") : null),
        done
          ? h("div", { class: "deadline" }, "Ocena sporządzona",
            h("span", { class: "badge badge-ok" }, icon("circleCheck"), fmtDate(ev.czesc_ii.data_sporzadzenia)))
          : h("div", { class: "deadline" },
            criteriaStage ? "Termin wyznaczenia kryteriów" : "Termin sporządzenia oceny",
            h("span", { class: `badge ${cls}` }, icon(u === "PO_TERMINIE" ? "alert" : "clock"),
              `${fmtDate(due)} · ${daysLeftText(days)}`))));
  }

  function stepDates() {
    const ev = s.ev;
    return [ev.czesc_i.potw_oceniajacy?.at, ev.czesc_i.potw_oceniany?.at, ev.czesc_ii.data_rozmowy_oceniajacej,
      ev.czesc_ii.data_sporzadzenia, ev.czesc_ii.zapoznanie?.at];
  }

  function currentStep() {
    return stageIndex(s.ev.status);  // labels.js: ZAKONCZONA and SPRZECIW = after the last stage
  }

  function renderStepper() {
    const cur = currentStep();
    const dates = stepDates();
    replace(R.stepper, h("ol", { class: "card stepper", "aria-label": "Etapy oceny okresowej" },
      STAGES.map((st, i) => {
        const state = i < cur ? "done" : i === cur ? "current" : "todo";
        // a step is finished when the next one starts: its date is when it was closed
        const meta = state === "done" ? fmtDate(dates[i]) : state === "current" ? "w toku" : "";
        return h("li", { class: `step ${state}`, "aria-current": state === "current" ? "step" : false },
          h("span", { class: "step-dot" }, state === "done" ? icon("check") : String(i + 1)),
          h("span", { class: "step-text" },
            h("span", { class: "step-label" }, st.label),
            h("span", { class: "step-meta" },
              h("span", { class: "sr-only" }, state === "done" ? "zakończony " : state === "current" ? "bieżący " : "nierozpoczęty "),
              meta)));
      })));
  }

  function prevText() {
    const p = s.ev.czesc_ii.poprzednia_ocena;
    if (!p || !p.wynik) return "brak";
    const parts = [p.wynik === "POZYTYWNA" ? "pozytywna" : p.wynik === "NEGATYWNA" ? "negatywna" : "brak"];
    if (p.poziom) parts.push(LEVEL_LABEL[p.poziom]);
    return `${parts.join(", ")}${p.data ? ` (${fmtDate(p.data)})` : ""}`;
  }

  function renderPerson() {
    const ev = s.ev;
    const o = ev.oceniany;
    const from = ev.czesc_ii.okres_od || ev.czesc_i.data_wyznaczenia_kryteriow;
    const to = ev.czesc_ii.okres_do || ev.czesc_i.termin_oceny;
    const fact = (k, v) => h("div", { class: "fact" }, h("dt", {}, k), h("dd", {}, v));
    const confirmed = ev.czesc_i.potw_oceniany?.at;
    replace(R.person, h("section", { class: "card card-pad", "aria-label": "Oceniany" },
      h("div", { class: "person" },
        avatar(o.imie, o.nazwisko, "avatar-lg"),
        h("div", {},
          h("div", { class: "person-name" }, personName(o)),
          h("div", { class: "muted" }, `${o.stanowisko} · ${o.komorka}`),
          h("dl", { class: "facts" },
            fact("Typ zatrudnienia", EMPLOYMENT_LABEL[o.typ_zatrudnienia] || o.typ_zatrudnienia),
            fact("Okres oceny", from ? `${fmtDate(from)} – ${fmtDate(to)}` : "od wyznaczenia kryteriów"),
            fact("Poprzednia ocena", prevText()),
            fact("Oceniający", personName(ev.oceniajacy))),
          (isEvaluator() || ctx.me.rola === "KADRY") && !["OCENA_DO_ZAPOZNANIA", "ZAKONCZONA"].includes(ev.status)
            ? h("a", { class: "btn btn-sm", href: `#/nieobecnosci/${o.id}`, style: { marginTop: "10px" } },
              icon("calendar"), "Zgłoś nieobecność") : null,
          confirmed ? h("p", { class: "locked", style: { marginTop: "10px" } }, icon("lock"),
            `Kryteria i termin zatwierdził(a) ${personName(ev.czesc_i.potw_oceniajacy.osoba)} ${fmtDate(ev.czesc_i.potw_oceniajacy.at)}, ` +
            `oceniany potwierdził(a) ${fmtDate(confirmed)}.`) : null))));
  }

  // ------------------------------------------------------------ main panel (depends on the stage)
  function renderMain() {
    const st = s.ev.status;
    if (st === "KRYTERIA_DO_WYZNACZENIA") return replace(R.main, sheetPanel(), criteriaSelection());
    if (st === "KRYTERIA_DO_POTWIERDZENIA" || st === "OKRES_OCENY") return replace(R.main, criteriaOverview());
    replace(R.main, scoringPanel(), wellbeingPanel(), paperPanel(), objectionPanel());
  }

  // ------------------------------------------------------------ burnout checklist (working material, never in the PDF)
  function wellbeingPanel() {
    if (s.ev.status !== "ROZMOWA_OCENIAJACA" || !isEvaluator() || !s.wb) return null;
    const { list, answers, draft } = s.wb;
    const rows = list.objawy.map((o) => {
      const cur = draft[o.id] || {};
      const name = `wb-${o.id}`;
      return h("fieldset", { class: "wb-row" },
        h("legend", {}, h("strong", {}, o.nazwa), h("span", { class: "small muted" }, ` – ${o.opis}`)),
        h("div", { class: "row", style: { gap: "14px", flexWrap: "wrap" } },
          list.odpowiedzi.map((a) => h("label", { class: "row", style: { gap: "4px" } },
            h("input", { type: "radio", name, value: a.kod, checked: cur.odpowiedz === a.kod,
              onchange: () => { draft[o.id] = { ...(draft[o.id] || {}), odpowiedz: a.kod }; } }), a.nazwa)),
          h("input", { type: "text", "aria-label": `Komentarz: ${o.nazwa}`, placeholder: "Komentarz (opcjonalnie)",
            value: cur.komentarz || "", style: { flex: "1 1 200px" },
            oninput: (e) => { draft[o.id] = { ...(draft[o.id] || { odpowiedz: "NIE_ZAUWAZAM" }), komentarz: e.target.value }; } })));
    });
    const save = async () => {
      const body = Object.fromEntries(Object.entries(draft).filter(([, v]) => v && v.odpowiedz));
      try {
        s.wb.answers = await api.setWellbeing(id, body);
        toast("Zapisano listę kontrolną dobrostanu.");
        s.hr = null; renderMain(); loadHr();
      } catch (e) { toast(e.message, "bad"); }
    };
    return h("section", { class: "card card-pad", style: { marginTop: "12px" }, "aria-labelledby": "wb-h" },
      h("div", { class: "row", style: { justifyContent: "space-between" } },
        h("h2", { id: "wb-h", class: "row", style: { gap: "8px" } }, icon("lifebuoy"), "Dobrostan"),
        h("span", { class: "badge badge-idle" }, icon("lock"), "tylko dla Ciebie i HR")),
      h("p", { class: "small muted" }, list.instrukcja),
      answers.sygnal_przeciazenia ? h("p", { class: "notice notice-bad" }, icon("alert"),
        `„Często” w ${answers.liczba_czesto} obszarach – HR partner pokaże sygnał przeciążenia z rekomendacjami.`) : null,
      h("div", { class: "stack", style: { gap: "10px", marginTop: "10px" } }, rows),
      h("div", { class: "row", style: { justifyContent: "space-between", marginTop: "10px" } },
        h("span", { class: "small muted" }, answers.zaktualizowano ? `Zapisano ${fmtDate(answers.zaktualizowano)}` : "Jeszcze nie zapisano"),
        h("button", { class: "btn", type: "button", onclick: save }, icon("save"), "Zapisz listę")));
  }

  // ------------------------------------------------------------ sheet suggested from the position (§ 3)
  function sheetPanel() {
    const d = s.ev.dobor_arkusza;
    if (!d) return null;
    const parts = [
      h("p", {}, h("strong", {}, `Arkusz ${s.ev.arkusz}. `), d.sugerowany === s.ev.arkusz ? d.powod
        : `System podpowiadał arkusz ${d.sugerowany} (${d.powod}).`),
      d.ostrzezenie ? h("p", { class: "notice notice-bad" }, icon("alert"), d.ostrzezenie) : null,
      d.zmiany.length ? h("ul", { class: "small muted" }, d.zmiany.map((z) =>
        h("li", {}, `${fmtDate(z.data)}: ${z.kto} zmienił(a) arkusz ${z.z} → ${z.na} – ${z.uzasadnienie}`))) : null,
    ];
    if (d.mozna_zmienic) {
      const sel = h("select", { "aria-label": "Nowy arkusz" }, ["A", "B", "C"].map((x) =>
        h("option", { value: x, selected: x === s.ev.arkusz }, `Arkusz ${x}`)));
      const why = h("input", { type: "text", "aria-label": "Uzasadnienie zmiany arkusza", placeholder: "Uzasadnienie zmiany" });
      parts.push(h("div", { class: "row", style: { gap: "8px", marginTop: "8px", flexWrap: "wrap" } }, sel, why,
        h("button", { class: "btn btn-sm", type: "button", onclick: async () => {
          try {
            s.ev = await api.changeSheet(id, { arkusz: sel.value, uzasadnienie: why.value });
            s.criteriaDict = await api.criteria(s.ev.arkusz);
            toast(`Zmieniono arkusz na ${s.ev.arkusz}.`);
            renderAll();
          } catch (e) { toast(e.message, "bad"); }
        } }, "Zmień arkusz")),
      h("p", { class: "small muted" }, "Arkusz można zmienić tylko przed zatwierdzeniem kryteriów."));
    }
    return h("section", { class: "card card-pad" }, h("h2", { class: "row", style: { gap: "8px" } }, "Dobór arkusza",
      helpLink("rozporzadzenie-oceny-okresowe-2016", "§ 3", "§ 3 – arkusze A, B, C")), parts);
  }

  // ------------------------------------------------------------ paper flow: print date, signature, refusal to sign
  function paperPanel() {
    const ev = s.ev, c = ev.czesc_ii;
    const canEdit = isEvaluator() && ["OCENA_DO_ZAPOZNANIA", "ZAKONCZONA", "SPRZECIW"].includes(ev.status) && c.data_sporzadzenia;
    if (!c.data_wydruku && !c.data_podpisu && !c.fikcja_zapoznania && !(canEdit && ev.status === "OCENA_DO_ZAPOZNANIA")) return null;
    const parts = [h("h2", {}, "Zapoznanie na papierze")];
    const facts = [];
    if (c.data_wydruku) facts.push(h("dt", {}, "Wydruk arkusza"), h("dd", {}, fmtDate(c.data_wydruku)));
    if (c.data_podpisu) facts.push(h("dt", {}, "Podpis ocenianego"), h("dd", {}, fmtDate(c.data_podpisu)));
    if (c.fikcja_zapoznania) facts.push(h("dt", {}, "Odmowa podpisu"), h("dd", {}, c.adnotacja_odmowy || "tak"));
    if (c.termin_sprzeciwu) facts.push(h("dt", {}, "Termin sprzeciwu"), h("dd", {}, fmtDate(c.termin_sprzeciwu)));
    if (facts.length) parts.push(h("dl", { class: "small" }, facts));
    if (canEdit && ev.status === "OCENA_DO_ZAPOZNANIA") {
      const printed = h("input", { type: "date", id: "paper-printed", value: c.data_wydruku || "" });
      const signed = h("input", { type: "date", id: "paper-signed" });
      const save = async (body, done) => {
        try {
          s.ev = await api.paper(id, body);
          toast(done);
          await loadSide();
          renderAll();
        } catch (e) {
          const extra = e.walidacje?.length ? ` ${e.walidacje.map((w) => w.komunikat).join(" ")}` : "";
          toast(`${e.message}${extra}`, "bad");
        }
      };
      parts.push(h("p", { class: "small muted" },
        "Wydrukuj arkusz (PDF), daj go ocenianemu do podpisu i wpisz daty. Data podpisu jest datą zapoznania – od niej "
        + "(albo od powrotu do pracy, gdy oceniany był nieobecny) liczy się termin sprzeciwu i przypomnienia."),
      h("div", { class: "row", style: { gap: "12px", flexWrap: "wrap", alignItems: "flex-end" } },
        h("label", { for: "paper-printed", class: "stack", style: { gap: "4px" } }, h("span", {}, "Data wydruku"), printed),
        h("label", { for: "paper-signed", class: "stack", style: { gap: "4px" } }, h("span", {}, "Data podpisu ocenianego"), signed),
        h("button", { class: "btn btn-primary", type: "button", onclick: () =>
          save({ data_wydruku: printed.value || null, data_podpisu: signed.value || null },
            signed.value ? "Zapisano podpis – ocena zapoznana." : "Zapisano datę wydruku.") }, icon("save"), "Zapisz daty")));
      if (ev.dozwolone_akcje.includes("FIKCJA_ZAPOZNANIA")) {
        const note = h("textarea", { rows: 2, "aria-label": "Adnotacja o odmowie podpisu",
          placeholder: "Np. Oceniany odmówił podpisu w obecności …" });
        const day = h("input", { type: "date", "aria-label": "Data odmowy podpisu" });
        parts.push(h("details", { style: { marginTop: "12px" } }, h("summary", {}, "Oceniany odmawia podpisu"),
          h("p", { class: "small muted" }, "Odnotuj odmowę na arkuszu (fikcja zapoznania) – od tego dnia ocena jest uznana za zapoznaną."),
          note, h("div", { class: "row", style: { gap: "8px", marginTop: "8px" } }, day,
            h("button", { class: "btn", type: "button", onclick: () => objectionAction("FIKCJA_ZAPOZNANIA",
              { komentarz: note.value, data: day.value || null }) }, "Odnotuj odmowę podpisu"))));
      }
    }
    return h("section", { class: "card card-pad", style: { marginTop: "12px" } }, parts);
  }

  // ------------------------------------------------------------ objection (art. 83): its own panel, not the main button
  const OBJECTION_ACTIONS = ["ZLOZ_SPRZECIW", "ROZPATRZ_SPRZECIW", "FIKCJA_ZAPOZNANIA"];

  async function objectionAction(akcja, body) {
    try {
      s.ev = await api.action(id, akcja, body);
      toast(ACTION_DONE[akcja] || "Zapisano.");
      renderAll();
    } catch (e) {
      const extra = e.walidacje?.length ? ` ${e.walidacje.map((w) => w.komunikat).join(" ")}` : "";
      toast(`${e.message}${extra}`, "bad");
    }
  }

  function objectionPanel() {
    const ev = s.ev, o = ev.sprzeciw, can = (a) => ev.dozwolone_akcje.includes(a);
    if (!o && !can("ZLOZ_SPRZECIW")) return null;
    const parts = [h("h2", { class: "row", style: { gap: "8px" } }, "Sprzeciw od oceny",
      helpLink("ustawa-sc-wyciag-oceny", "Art. 83", "art. 83 – sprzeciw od oceny"))];
    if (o) {
      const decided = o.decyzja ? (o.decyzja === "UWZGLEDNIONY" ? "uwzględniony" : "nieuwzględniony") : null;
      parts.push(h("dl", { class: "small" },
        h("dt", {}, "Złożony"), h("dd", {}, fmtDate(o.zlozony)),
        h("dt", {}, "Treść"), h("dd", {}, o.tresc),
        h("dt", {}, "Termin rozpatrzenia"), h("dd", {}, `${fmtDate(o.termin_rozpatrzenia)} (14 dni, art. 83 ust. 3)`),
        decided ? [h("dt", {}, "Rozstrzygnięcie"), h("dd", {}, `${decided}, ${fmtDate(o.rozstrzygnieto)}: ${o.uzasadnienie_decyzji}`)] : null,
        o.termin_odwolania_do_sadu ? [h("dt", {}, "Odwołanie do sądu pracy"),
          h("dd", {}, `do ${fmtDate(o.termin_odwolania_do_sadu)} (14 dni, art. 83 ust. 5)`)] : null));
    }
    if (can("ZLOZ_SPRZECIW")) {
      const ta = h("textarea", { rows: 3, "aria-label": "Treść sprzeciwu", placeholder: "Z czym się nie zgadzasz i dlaczego?" });
      parts.push(h("p", { class: "small muted" },
        `Termin: ${fmtDate(ev.czesc_ii.termin_sprzeciwu)} (7 dni od zapoznania się z oceną). `
        + `${ev.rozpatrujacy_sprzeciw ? ev.rozpatrujacy_sprzeciw.podstawa : "Sprzeciw rozpatruje dyrektor generalny urzędu"}.`),
        ta, h("button", { class: "btn btn-primary", type: "button", style: { marginTop: "8px" },
          onclick: () => objectionAction("ZLOZ_SPRZECIW", { komentarz: ta.value }) }, icon("send"), "Złóż sprzeciw"));
    }
    if (can("ROZPATRZ_SPRZECIW")) {
      const ta = h("textarea", { rows: 3, "aria-label": "Uzasadnienie rozstrzygnięcia", placeholder: "Uzasadnienie rozstrzygnięcia" });
      parts.push(ta, h("div", { class: "row", style: { gap: "8px", marginTop: "8px" } },
        h("button", { class: "btn btn-primary", type: "button",
          onclick: () => objectionAction("ROZPATRZ_SPRZECIW", { uwzglednij: true, komentarz: ta.value }) },
          "Uwzględnij – ocena wraca do oceniającego"),
        h("button", { class: "btn", type: "button",
          onclick: () => objectionAction("ROZPATRZ_SPRZECIW", { uwzglednij: false, komentarz: ta.value }) },
          "Nie uwzględniaj")));
    }
    return h("section", { class: "card card-pad", style: { marginTop: "12px" } }, parts);
  }

  function criteriaSelection() {
    const ev = s.ev;
    const mandatory = ev.kryteria.filter((k) => k.typ === "OBOWIAZKOWE");
    const chosen = ev.kryteria.filter((k) => k.typ === "DODATKOWE").map((k) => k.criterion_kod);
    const can = editable("kryteria_dodatkowe");
    const optional = (s.criteriaDict || []).filter((c) => c.typ_dla_arkusza === "DODATKOWE");
    const max = ctx.meta.maks_kryteriow_dodatkowych;
    const slots = Array.from({ length: max }, (_, i) => chosen[i] || "");

    async function choose(slot, value) {
      const next = [...slots];
      next[slot] = value;
      try {
        s.ev = await api.additional(id, next.filter(Boolean));
        renderMain(); renderAside(); renderActions();
      } catch (e) { toast(e.message, "bad"); renderMain(); }
    }

    return h("section", { class: "card", "aria-labelledby": "crit-h" },
      h("div", { class: "card-head" }, h("div", {},
        h("h2", { id: "crit-h" }, "Wyznaczenie kryteriów"),
        h("p", {}, `Kryteria obowiązkowe wynikają z arkusza ${ev.arkusz}. Możesz dodać do ${max} kryteriów dodatkowych, bez powtórzeń.`))),
      h("div", { class: "crit-group" }, h("h3", { style: { padding: "14px 20px 6px", fontSize: "11.5px", textTransform: "uppercase", letterSpacing: ".05em", color: "var(--text-3)" } }, "Kryteria obowiązkowe")),
      h("ul", { class: "plain-list" }, mandatory.map((k) => h("li", {}, h("span", {}, k.nazwa),
        h("span", { class: "locked" }, icon("lock"), `obowiązkowe – arkusz ${ev.arkusz}`)))),
      h("div", { class: "pick-list" },
        h("h3", { style: { fontSize: "11.5px", textTransform: "uppercase", letterSpacing: ".05em", color: "var(--text-3)" } }, "Kryteria dodatkowe"),
        slots.map((val, i) => h("div", { class: "pick-row" },
          h("label", { for: `add-${i}`, class: "small muted" }, `Kryterium ${i + 1}`),
          h("select", { id: `add-${i}`, disabled: !can, onchange: (e) => choose(i, e.target.value) },
            h("option", { value: "" }, "— brak —"),
            optional.filter((c) => c.kod === val || !slots.includes(c.kod))
              .map((c) => h("option", { value: c.kod, selected: c.kod === val }, c.nazwa)))))),
      h("div", { class: "field" },
        h("div", { class: "field-head" }, h("span", { style: { fontWeight: 650 } }, "Termin sporządzenia oceny"),
          h("span", { class: "small muted" }, "wyliczony: 24 miesiące od początku cyklu, z pominięciem dni wolnych")),
        h("strong", { class: "num" }, fmtDate(ev.czesc_i.termin_oceny))));
  }

  function criteriaOverview() {
    const ev = s.ev;
    const ev2 = s.evidence;
    const withEvidence = ev.status === "OKRES_OCENY" && canSeeWorkNotes() && ev2;
    const row = (k) => {
      const e = withEvidence ? ev2.kryteria.find((x) => x.criterion_kod === k.criterion_kod) : null;
      return h("li", {},
        h("span", { class: "row" }, k.nazwa, k.typ === "DODATKOWE" ? h("span", { class: "badge badge-sheet" }, "dodatkowe") : null),
        e ? evidenceCounts(e.plus, e.minus) : h("span", { class: "locked" }, icon("lock"), "zatwierdzone"));
    };
    const sig = ev.czesc_i.potw_oceniajacy;
    return h("section", { class: "card", "aria-labelledby": "crit-h" },
      h("div", { class: "card-head" }, h("div", {},
        h("h2", { id: "crit-h" }, ev.status === "OKRES_OCENY" ? "Okres oceny – obserwacje" : "Kryteria oceny"),
        h("p", {}, ev.status === "OKRES_OCENY"
          ? "Kryteria są potwierdzone. Notatki z okresu oceny składają się na dowody przy każdym kryterium."
          : "Kryteria czekają na potwierdzenie przez ocenianego."))),
      h("ul", { class: "plain-list" }, ev.kryteria.map(row)),
      sig?.at ? h("p", { class: "locked", style: { padding: "12px 20px" } }, icon("lock"),
        `Zatwierdził(a) ${personName(sig.osoba)} ${fmtDate(sig.at)}`) : null,
      withEvidence && ev2.notatki_do_przypisania ? h("p", { class: "small muted", style: { padding: "0 20px 14px" } },
        `Notatki bez przypisanego kryterium: ${ev2.notatki_do_przypisania}.`) : null);
  }

  function evidenceCounts(plus, minus) {
    return h("span", { class: "evid", title: "Dowody z notatek przełożonego" },
      icon("message"),
      h("span", { class: "plus" }, `${plus} +`), "/", h("span", { class: "minus" }, `${minus} −`),
      h("span", { class: "sr-only" }, `: ${plus} pozytywnych i ${minus} negatywnych notatek`));
  }

  function notesFor(kod, suggested) {
    const list = s.notes.filter((n) => n.criterion_kod === kod);
    const lowFirst = suggested !== null && suggested !== undefined && suggested <= 5;
    const rank = (n) => (n.wydzwiek === (lowFirst ? "NEGATYWNY" : "POZYTYWNY") ? 0 : n.wydzwiek === "NEUTRALNY" ? 1 : 2);
    return [...list].sort((a, b) => rank(a) - rank(b) || b.data.localeCompare(a.data));
  }

  function scoringPanel() {
    const ev = s.ev;
    const canScore = editable("punkty");
    const mand = ev.kryteria.filter((k) => k.typ === "OBOWIAZKOWE");
    const add = ev.kryteria.filter((k) => k.typ === "DODATKOWE");
    const evid = (kod) => s.evidence?.kryteria.find((x) => x.criterion_kod === kod);
    const firstOpen = s.open.size === 0 && canSeeWorkNotes()
      ? ev.kryteria.find((k) => evid(k.criterion_kod)?.sugerowane_punkty) : null;
    if (firstOpen) s.open.add(firstOpen.criterion_kod);

    const group = (title) => h("tr", { class: "crit-group" }, h("th", { scope: "colgroup" }, title));
    const rows = (list) => list.map((k) => criterionRow(k, evid(k.criterion_kod), canScore));
    const sig = ev.czesc_ii.podpis_oceniajacego;

    return h("section", { class: "card", "aria-labelledby": "score-h" },
      h("div", { class: "card-head" },
        h("div", {}, h("h2", { id: "score-h" }, "Sporządzenie oceny"),
          h("p", {}, canScore ? "Wybierz ocenę cząstkową przy każdym kryterium. Wynik liczy się automatycznie."
            : "Oceny cząstkowe są zablokowane do edycji.")),
        !canScore && sig?.at ? h("span", { class: "locked" }, icon("lock"),
          `Zatwierdził(a) ${personName(sig.osoba)} ${fmtDate(sig.at)}`) : null),
      h("table", { class: "crit-table" },
        h("caption", { class: "sr-only" }, "Oceny cząstkowe za kryteria"),
        h("tbody", {}, group("Kryteria obowiązkowe"), rows(mand),
          group("Kryteria dodatkowe wybrane przez oceniającego"),
          add.length ? rows(add) : h("tr", { class: "crit-row" }, h("td", { class: "muted" }, "brak")))),
      resultBar(),
      textField("uzasadnienie"),
      textField("wnioski_iprz"));
  }

  function criterionRow(k, e, canScore) {
    const kod = k.criterion_kod;
    const isOpen = s.open.has(kod);
    const suggested = e?.sugerowane_punkty ?? null;
    const showWork = canSeeWorkNotes() && e;
    const notes = showWork ? notesFor(kod, suggested) : [];
    const scale = ctx.meta.skala_punktow;
    const name = `pts-${kod}`;
    const seg = h("div", {
      class: `seg ${k.punkty !== null && k.punkty <= 1 ? "is-low" : ""}`, role: "radiogroup",
      "aria-label": `Ocena: ${k.nazwa}`, "aria-disabled": canScore ? false : "true",
    }, scale.flatMap((p) => {
      const idv = `${name}-${p}`;
      return [
        h("input", { type: "radio", name, id: idv, value: p, checked: k.punkty === p, disabled: !canScore,
          onchange: () => setScore(kod, p) }),
        h("label", { for: idv, class: suggested === p ? "seg-suggested" : "" },
          h("span", { class: "pts" }, p), h("span", { class: "lbl" }, SCALE_SHORT[p]),
          suggested === p ? h("span", { class: "sr-only" }, " (sugerowane przez asystenta)") : null),
      ];
    }));

    const sub = [];
    if (showWork) sub.push(evidenceCounts(e.plus, e.minus));
    if (showWork && suggested !== null) {
      sub.push(h("span", { class: "suggest" }, icon("sparkles"),
        `Sugerowane: ${suggested} · na podstawie ${e.plus + e.neutralne + e.minus} notatek`,
        canScore && k.punkty !== suggested
          ? h("button", { class: "btn btn-sm", type: "button", onclick: () => setScore(kod, suggested),
            "aria-label": `Przyjmij sugerowaną ocenę ${suggested} dla kryterium ${k.nazwa}` }, "Przyjmij")
          : k.punkty === suggested ? h("span", { class: "small", style: { paddingRight: "6px" } }, "zgodne z oceną") : null));
    }
    if (notes.length) {
      sub.push(h("button", { class: "link-btn", type: "button", "aria-expanded": String(isOpen),
        "aria-controls": `notes-${kod}`,
        onclick: () => { isOpen ? s.open.delete(kod) : s.open.add(kod); renderMain(); } },
      icon(isOpen ? "chevronUp" : "chevronDown"), isOpen ? "Ukryj notatki" : `Pokaż notatki (${notes.length})`));
    }

    return h("tr", { class: `crit-row ${isOpen ? "open" : ""}` }, h("td", {},
      h("div", { class: "crit-main" },
        h("div", { class: "crit-name" }, k.nazwa, k.typ === "DODATKOWE" ? h("span", { class: "badge badge-sheet" }, "dodatkowe") : null),
        seg,
        sub.length ? h("div", { class: "crit-sub" }, sub) : null),
      isOpen && notes.length ? h("div", { class: "evidence-notes", id: `notes-${kod}` },
        e?.uzasadnienie_sugestii ? h("p", { class: "small muted" }, `Sugestia ${e.uzasadnienie_sugestii}.`) : null,
        notes.slice(0, 3).map(noteCard),
        notes.length > 3 ? h("p", { class: "small muted" }, `…i jeszcze ${notes.length - 3}.`) : null) : null));
  }

  function noteCard(n) {
    const tone = n.wydzwiek === "POZYTYWNY" ? ["badge-ok", "+ pozytywna"] : n.wydzwiek === "NEGATYWNY" ? ["badge-bad", "− negatywna"] : ["badge-idle", "neutralna"];
    return h("div", { class: "note" },
      h("div", { class: "note-head" }, icon("calendar"), fmtDate(n.data), h("span", { class: `badge ${tone[0]}` }, tone[1]),
        h("span", {}, `notatka przełożonego · ${personName(n.autor)}`)),
      h("q", {}, n.tresc));
  }

  async function setScore(kod, points) {
    if (s.busy) return;
    s.busy = true;
    try {
      await api.scores(id, { [kod]: points });
      await refreshEvaluation();
      s.hr = null; // signals depend on the scores (e.g. lower than last time)
      renderMain(); renderAside(); renderActions();
      loadHr();
    } catch (e) {
      toast(e.message, "bad");
      renderMain();
    } finally {
      s.busy = false;
    }
  }

  function resultBar() {
    const c = s.ev.czesc_ii;
    const total = s.ev.kryteria.length;
    const scored = s.ev.kryteria.filter((k) => k.punkty !== null && k.punkty !== undefined).length;
    const main = c.srednia !== null && c.srednia !== undefined
      ? h("div", { class: "result-main", "aria-live": "polite" },
        h("span", {}, "Średnia ", h("strong", {}, fmtNumber(c.srednia))),
        h("span", { "aria-hidden": "true" }, "·"),
        h("span", {}, "poziom: ", h("strong", {}, LEVEL_LABEL[c.poziom])),
        c.wynik === "NEGATYWNA"
          ? h("span", { class: "badge badge-bad" }, icon("circleX"), "OCENA NEGATYWNA")
          : h("span", { class: "badge badge-ok" }, icon("circleCheck"), "OCENA POZYTYWNA"))
      : h("div", { class: "result-main", "aria-live": "polite" }, icon("info"),
        `Uzupełnij wszystkie oceny cząstkowe (${scored} z ${total}), aby zobaczyć wynik.`);
    return h("div", { class: "result-bar" }, main,
      h("p", { class: "result-note" }, "Ocena jest negatywna także wtedy, gdy którekolwiek kryterium ma 1 punkt (§ 11 rozporządzenia)."));
  }

  // ------------------------------------------------------------ text fields + AI drafts
  function requirement(field) {
    const empty = !(s.text[field] || "").trim();
    if (field === "uzasadnienie") {
      if (s.ev.czesc_ii.wynik === "NEGATYWNA") {
        return h("span", { class: `req ${empty ? "" : "ok"}` }, icon(empty ? "alert" : "check"), "Obowiązkowe przy ocenie negatywnej");
      }
      return h("span", { class: "small muted" }, "Opcjonalne przy ocenie pozytywnej");
    }
    return h("span", { class: `req ${empty ? "" : "ok"}` }, icon(empty ? "alert" : "check"), "Obowiązkowe");
  }

  function textField(field) {
    const cfg = TEXT_FIELDS[field];
    const can = editable(field);
    const fid = `f-${field}`;
    const d = s.drafts[cfg.draft];
    const reqBox = h("span", { class: "req-box" }, requirement(field));
    const ta = h("textarea", {
      id: fid, readonly: !can, rows: 6,
      class: can && blocking().some((w) => w.pole === field) ? "invalid" : "",
      "aria-describedby": `${fid}-hint`,
      placeholder: can ? "Wpisz treść lub poproś asystenta o szkic…" : "",
      oninput: (e) => {
        s.text[field] = e.target.value;
        s.dirty.add(field);
        replace(reqBox, requirement(field));
      },
      onblur: () => { if (s.dirty.has(field)) saveText(); },
    });
    ta.value = s.text[field] || "";

    let proposal = null;
    if (d?.state === "loading") {
      proposal = h("div", { class: "proposal", "aria-live": "polite" }, loading("Asystent przygotowuje szkic…"));
    } else if (d?.state === "ready") {
      const use = (focus) => () => {
        s.text[field] = d.data.tekst;
        s.dirty.add(field);
        d.state = "used";
        renderMain();
        const el = document.getElementById(fid);
        if (focus && el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length); } else saveText();
      };
      proposal = h("div", { class: "proposal", role: "group", "aria-label": "Propozycja asystenta" },
        h("div", { class: "proposal-head" },
          h("span", { class: "badge badge-ai" }, icon("sparkles"), "Propozycja asystenta"),
          h("div", { class: "row", style: { gap: "6px" } },
            h("button", { class: "btn btn-sm btn-ai", type: "button", onclick: use(false) }, "Wstaw"),
            h("button", { class: "btn btn-sm", type: "button", onclick: use(true) }, icon("pencil"), "Edytuj"),
            h("button", { class: "btn btn-sm", type: "button", onclick: () => { d.state = "dismissed"; renderMain(); } }, icon("x"), "Odrzuć"))),
        h("div", { class: "proposal-text" }, d.data.tekst),
        h("p", { class: "proposal-src" },
          d.data.zrodlo === "AI" ? "Wygenerowane przez model lokalny" : "Szablon z danych (model niedostępny)",
          d.data.oparte_na_notatkach?.length ? ` · na podstawie ${d.data.oparte_na_notatkach.length} notatek` : "",
          " · nic nie zostanie zapisane bez Twojej decyzji."));
    } else if (d?.state === "error") {
      proposal = h("p", { class: "notice notice-bad", style: { marginBottom: "10px" } }, icon("alert"), d.error);
    }

    const locked = !can && s.ev.czesc_ii.podpis_oceniajacego?.at;
    return h("div", { class: "field" },
      h("div", { class: "field-head" },
        h("div", { class: "row", style: { gap: "10px" } }, h("label", { for: fid }, cfg.label), helpLink(...cfg.help), reqBox),
        can && aiOn() && d?.state !== "loading"
          ? h("button", { class: "btn btn-sm btn-ai", type: "button", onclick: () => requestDraft(cfg.draft) },
            icon("sparkles"), "Szkic od asystenta")
          : locked ? h("span", { class: "locked" }, icon("lock"), "zablokowane po zatwierdzeniu oceny") : null),
      proposal,
      ta,
      h("p", { id: `${fid}-hint`, class: "sr-only" }, field === "uzasadnienie"
        ? "Uzasadnienie jest obowiązkowe przy ocenie negatywnej." : "Pole obowiązkowe."));
  }

  async function requestDraft(kind) {
    s.drafts[kind] = { state: "loading" };
    renderMain();
    try {
      s.drafts[kind] = { state: "ready", data: await api.draft(id, kind) };
    } catch (e) {
      s.drafts[kind] = { state: "error", error: e.message };
    }
    renderMain();
  }

  async function saveText({ quiet = true } = {}) {
    if (!s.dirty.size) {
      if (!quiet) toast("Brak zmian do zapisania.");
      return true;
    }
    const body = { updated_at: s.ev.updated_at };
    for (const f of s.dirty) body[f] = s.text[f];
    try {
      s.ev = await api.patch(id, body);
      s.dirty.clear();
      syncText();
      for (const f of Object.keys(TEXT_FIELDS)) {
        document.getElementById(`f-${f}`)?.classList.toggle("invalid", blocking().some((w) => w.pole === f));
      }
      renderAside(); renderActions();
      if (!quiet) toast("Zapisano roboczo.");
      return true;
    } catch (e) {
      toast(e instanceof ApiError && e.kod === "KONFLIKT_WERSJI" ? "Ktoś zmienił ocenę w międzyczasie – odśwież stronę." : e.message, "bad");
      return false;
    }
  }

  // ------------------------------------------------------------ aside: assistant
  function renderAside() {
    const ev = s.ev;
    const cur = currentStep();
    const stepNo = Math.min(cur + 1, STAGES.length);
    const done = ["ZAKONCZONA", "SPRZECIW"].includes(ev.status);
    const days = daysBetween(ctx.meta.dzis, ev.czesc_i.termin_oceny);
    const blocks = blocking();
    const checks = [];
    if (ev.status === "ROZMOWA_OCENIAJACA" && isEvaluator()) {
      const missingScores = blocks.filter((w) => w.kod === "BRAK_OCENY").length;
      if (missingScores) checks.push(h("li", {}, h("span", { class: "bad" }, icon("alert")), `Oceny cząstkowe: brakuje ${missingScores}`));
      for (const w of blocks.filter((x) => x.kod !== "BRAK_OCENY")) {
        checks.push(h("li", {}, h("span", { class: "bad" }, icon("alert")), CHECK_LABEL[w.kod] || w.komunikat));
      }
    }

    const progress = h("section", { class: "card card-pad", "aria-labelledby": "asst-h" },
      h("div", { class: "row", style: { justifyContent: "space-between" } },
        h("h2", { id: "asst-h" }, "Asystent"),
        h("span", { class: "small muted" }, done ? "proces zakończony" : `Krok ${stepNo} z ${STAGES.length}`)),
      h("div", { class: "progress", role: "progressbar", "aria-valuemin": "0", "aria-valuemax": String(STAGES.length),
        "aria-valuenow": String(Math.min(cur, STAGES.length)), "aria-label": "Postęp procesu" },
      h("span", { style: { width: `${(Math.min(cur, STAGES.length) / STAGES.length) * 100}%` } })),
      h("p", { class: "small muted" }, done ? STATUS_LABEL[ev.status]
        : `${STAGES[cur]?.label || ""}${["OCENA_DO_ZAPOZNANIA"].includes(ev.status) ? "" : ` · ${daysLeftText(days)}`}`),
      ev.status === "ROZMOWA_OCENIAJACA" && isEvaluator() ? h("div", { style: { marginTop: "14px" } },
        h("h3", { style: { marginBottom: "8px" } }, "Do uzupełnienia przed zatwierdzeniem"),
        checks.length ? h("ul", { class: "checklist" }, checks)
          : h("ul", { class: "checklist" }, h("li", {}, h("span", { class: "ok" }, icon("circleCheck")), "Wszystko gotowe do zatwierdzenia."))) : null);

    const parts = [progress, deadlinesCard()];
    if (isEvaluator() && ctx.meta.funkcje_ai?.hr_partner && !["OCENA_DO_ZAPOZNANIA", "ZAKONCZONA"].includes(ev.status)) {
      parts.push(hrCard());
    }
    parts.push(h("p", { class: "aside-note" }, icon("info"), "Asystent tylko podpowiada. Ocenę wystawia przełożony."));
    replace(R.aside, parts);
  }

  // every deadline, computed by the server from what has happened (app/domain/timeline.py)
  function deadlinesCard() {
    const items = s.ev.terminy || [];
    if (!items.length) return null;
    const badge = (t) => {
      if (t.stan === "SPELNIONY") return h("span", { class: "badge badge-ok" }, icon("check"), t.spelniony_at ? fmtDate(t.spelniony_at) : "tak");
      if (t.stan === "NASTEPNY_OKRES") return h("span", { class: "badge badge-idle" }, t.data ? fmtDate(t.data) : "–");
      if (!t.data) return h("span", { class: "badge badge-warn" }, "niezwłocznie");
      const days = daysBetween(ctx.meta.dzis, t.data);
      return h("span", { class: `badge ${t.stan === "PO_TERMINIE" ? "badge-bad" : days <= 7 ? "badge-warn" : "badge-idle"}` },
        fmtDate(t.data), " · ", daysLeftText(days));
    };
    return h("section", { class: "card card-pad", "aria-labelledby": "terms-h" },
      h("h2", { id: "terms-h", class: "row", style: { gap: "8px", marginBottom: "10px" } }, icon("clock"), "Terminy"),
      h("ul", { class: "deadlines" }, items.map((t) => h("li", {},
        h("div", {}, h("div", {}, t.nazwa), h("div", { class: "small muted" }, `${t.opis}${t.opis ? " · " : ""}${t.podstawa}`)),
        h("div", { class: "when" }, badge(t))))),
      h("p", { class: "small muted", style: { marginTop: "8px" } },
        "Liczone automatycznie: dni wolne przesuwają termin na najbliższy dzień roboczy."));
  }

  function hrCard() {
    let body;
    if (s.hrError) body = h("p", { class: "small muted" }, s.hrError);
    else if (!s.hr) body = loading("Analiza notatek…");
    else if (!s.hr.sygnaly.length) body = h("p", { class: "small muted" }, "Brak sygnałów w notatkach z ostatnich miesięcy.");
    else body = h("div", { class: "stack", style: { gap: "10px" } }, s.hr.sygnaly.map(signalCard));
    return h("section", { class: "card card-pad", "aria-labelledby": "hr-h" },
      h("div", { class: "row", style: { justifyContent: "space-between", marginBottom: "10px" } },
        h("h2", { id: "hr-h", class: "row", style: { gap: "8px" } }, icon("lifebuoy"), "HR partner"),
        s.hr ? h("span", { class: "badge badge-ai" }, icon("sparkles"), s.hr.zrodlo_tekstow === "AI" ? "podpowiedź AI" : "reguły") : null),
      h("p", { class: "small muted", style: { marginBottom: "10px" } }, "Podpowiedzi dla przełożonego przed rozmową – nie są oceną pracownika."),
      body);
  }

  function signalCard(sg) {
    const decided = sg.status !== "NOWY";
    const decide = (status) => async () => {
      try {
        await api.hrDecision(sg.id, status);
        sg.status = status;
        renderAside();
      } catch (e) { toast(e.message, "bad"); }
    };
    const evidence = sg.dowody.length ? `${sg.dowody.length} ${sg.dowody.length === 1 ? "obserwacja" : "obserwacje"}: ${sg.dowody[0]}` : sg.opis;
    return h("div", { class: "signal" },
      h("div", { class: "signal-title" }, SIGNAL_LABEL[sg.typ] || sg.typ),
      h("div", { class: "signal-why" }, sg.opis),
      h("div", { class: "signal-why" }, evidence),
      sg.rekomendacje[0] ? h("div", { class: "signal-rec" }, icon("chevronRight"),
        sg.rekomendacje[0].charAt(0).toUpperCase() + sg.rekomendacje[0].slice(1)) : null,
      decided
        ? h("span", { class: `badge ${sg.status === "ZAAKCEPTOWANY" ? "badge-ok" : "badge-idle"}` },
          icon(sg.status === "ZAAKCEPTOWANY" ? "check" : "x"), sg.status === "ZAAKCEPTOWANY" ? "Przyjęto" : "Odrzucono")
        : h("div", { class: "row", style: { gap: "6px" } },
          h("button", { class: "btn btn-sm btn-ai", type: "button", onclick: decide("ZAAKCEPTOWANY") }, "Przyjmij"),
          h("button", { class: "btn btn-sm", type: "button", onclick: decide("ODRZUCONY") }, "Odrzuć")));
  }

  // ------------------------------------------------------------ action bar
  function waitingText() {
    const st = s.ev.status;
    const who = {
      KRYTERIA_DO_WYZNACZENIA: "Teraz działa oceniający: wyznaczenie kryteriów.",
      KRYTERIA_DO_POTWIERDZENIA: "Teraz działa oceniany: potwierdzenie kryteriów.",
      OKRES_OCENY: "Teraz trwa okres oceny. Rozmowę rozpoczyna oceniający.",
      ROZMOWA_OCENIAJACA: "Teraz działa oceniający: sporządzenie oceny.",
      OCENA_DO_ZAPOZNANIA: "Teraz działa oceniany: zapoznanie się z oceną.",
      ZAKONCZONA: "Ocena jest zakończona.",
      SPRZECIW: "Sprzeciw rozpatruje dyrektor generalny urzędu (14 dni).",
    };
    return who[st] || "";
  }

  function renderActions() {
    const actions = s.ev.dozwolone_akcje.filter((a) => !OBJECTION_ACTIONS.includes(a));
    const primaryAction = actions[0];
    const blocks = primaryAction === "ZATWIERDZ_OCENE" ? blocking() : [];
    const anyText = Object.keys(TEXT_FIELDS).some(editable);

    let primary;
    if (!primaryAction) {
      primary = h("span", { class: "small muted" }, waitingText());
    } else if (s.confirming) {
      primary = h("div", { class: "primary-wrap" },
        h("div", { class: "row", style: { gap: "8px" } },
          h("button", { class: "btn", type: "button", onclick: () => { s.confirming = false; renderActions(); } }, "Anuluj"),
          h("button", { class: "btn btn-primary", type: "button", onclick: () => runAction(primaryAction) },
            icon("check"), `Potwierdź: ${ACTION_LABEL[primaryAction].toLowerCase()}`)),
        h("span", { class: "small muted" }, "Po zatwierdzeniu pola zostaną zablokowane."));
    } else {
      const hint = blocks.length ? BLOCK_HINT[blocks.find((b) => b.kod !== "BRAK_OCENY")?.kod || blocks[0].kod] || blocks[0].komunikat : null;
      primary = h("div", { class: "primary-wrap" },
        h("button", { class: "btn btn-primary", type: "button", disabled: Boolean(blocks.length),
          "aria-describedby": hint ? "primary-hint" : false,
          onclick: () => { s.confirming = true; renderActions(); } },
        icon(primaryAction === "ZATWIERDZ_OCENE" ? "send" : "check"), ACTION_LABEL[primaryAction] || primaryAction),
        hint ? h("span", { class: "primary-hint", id: "primary-hint" }, icon("alert"), hint) : null);
    }

    replace(R.actions, h("div", { class: "actionbar", role: "region", "aria-label": "Działania" },
      h("div", { class: "group" },
        h("a", { class: "btn", href: "#/" }, icon("arrowLeft"), "Wstecz"),
        anyText ? h("button", { class: "btn", type: "button", onclick: () => saveText({ quiet: false }) }, icon("save"), "Zapisz roboczo") : null,
        h("button", { class: "btn", type: "button", onclick: downloadPdf }, icon("download"), "Pobierz PDF arkusza")),
      primary));
  }

  async function downloadPdf() {
    try {
      const res = await fetch(`/api/evaluations/${id}/pdf`, { headers: { "X-User-Id": currentUserId() || "" } });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.komunikat || "Nie udało się pobrać PDF.");
      }
      const blob = await res.blob();
      const name = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") || "")?.[1] || `ocena-${id}.pdf`;
      const a = h("a", { href: URL.createObjectURL(blob), download: name });
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) {
      toast(e.message, "bad");
    }
  }

  async function runAction(akcja) {
    if (!(await saveText())) return;
    s.confirming = false;
    try {
      s.ev = await api.action(id, akcja);
      toast(ACTION_DONE[akcja] || "Zapisano.");
      s.dirty.clear(); syncText(); s.drafts = {}; s.hr = null;
      await loadSide();
      renderAll();
      loadHr();
    } catch (e) {
      const extra = e.walidacje?.length ? ` ${e.walidacje.map((w) => w.komunikat).join(" ")}` : "";
      toast(`${e.message}${extra}`, "bad");
      await refreshEvaluation();
      renderAll();
    }
  }

  function renderAll() {
    renderHead(); renderStepper(); renderPerson(); renderMain(); renderAside(); renderActions();
  }

  // ------------------------------------------------------------ first paint
  await loadSide();
  replace(view,
    R.head, R.stepper,
    h("div", { class: "with-aside" }, h("div", { class: "stack" }, R.person, R.main), R.aside),
    R.actions);
  renderAll();
  loadHr();

  // A negative result needs a justification: offer the assistant's draft straight away.
  const c = s.ev.czesc_ii;
  if (s.ev.status === "ROZMOWA_OCENIAJACA" && editable("uzasadnienie") && aiOn()
      && c.wynik === "NEGATYWNA" && !(s.text.uzasadnienie || "").trim()) {
    requestDraft("UZASADNIENIE");
  }
}
