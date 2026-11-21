// "Terminy i przypomnienia" – deadlines from the server, nearest first (UC3). "+7 dni" in the top bar moves the clock.
import { api } from "../api.js";
import { h, icon, replace, fmtDate, avatar, deadlineBadge } from "../ui.js";
import { STATUS_LABEL, WHO_LABEL, personName } from "../labels.js";

export async function renderDeadlines(view, ctx) {
  const data = await api.dashboard();
  const items = data.pozycje.filter((i) => i.dni_do_terminu !== null && i.dni_do_terminu !== undefined)
    .sort((a, b) => a.dni_do_terminu - b.dni_do_terminu);
  replace(view,
    h("div", { class: "page-head" }, h("div", {},
      h("h1", {}, "Terminy i przypomnienia"),
      h("p", {}, `Terminy liczone przez system (24 miesiące, dni wolne, nieobecności). Stan na ${fmtDate(ctx.meta.dzis)}.`))),
    h("div", { class: "card" },
      items.length ? h("ul", { class: "attention" }, items.map((i) => h("li", {},
        h("div", { class: "row", style: { justifyContent: "space-between" } },
          h("div", { class: "row" }, avatar(i.oceniany.imie, i.oceniany.nazwisko),
            h("div", {},
              h("a", { href: `#/ocena/${i.evaluation_id}` }, h("strong", {}, personName(i.oceniany))),
              h("div", { class: "small muted" },
                `${i.nastepny_krok || STATUS_LABEL[i.status]} · działa: ${WHO_LABEL[i.kto_dziala]}`))),
          h("div", { class: "row" }, h("span", { class: "num" }, fmtDate(i.termin)), deadlineBadge(i.dni_do_terminu))))))
        : h("p", { class: "empty" }, "Brak terminów do pilnowania.")),
    h("p", { class: "aside-note", style: { marginTop: "12px" } }, icon("info"),
      "Na potrzeby demonstracji czas można przesunąć przyciskami „+7 dni” / „+30 dni” w górnym pasku."));
}
