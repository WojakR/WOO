// App shell: navigation, top bar (year, AI mode, demo identity and clock) and a hash router.
import { api, currentUserId, setCurrentUserId } from "./api.js";
import { h, icon, replace, fmtDate, avatar, toast, loading } from "./ui.js";
import { renderOverview } from "./views/overview.js";
import { renderEvaluation } from "./views/evaluation.js";
import { renderDeadlines } from "./views/deadlines.js";
import { renderAbsences } from "./views/absences.js";
import { renderPlaceholder } from "./views/placeholder.js";

export const ctx = { me: null, meta: null, users: [], year: "all" };

const NAV = [
  { href: "#/", label: "Moje oceny", icon: "clipboard", match: (p) => p === "/" || p.startsWith("/ocena") },
  { href: "#/pracownicy", label: "Pracownicy", icon: "users", match: (p) => p.startsWith("/pracownicy") },
  { href: "#/terminy", label: "Terminy i przypomnienia", icon: "bell", match: (p) => p.startsWith("/terminy") },
  { href: "#/nieobecnosci", label: "Nieobecności", icon: "calendar", match: (p) => p.startsWith("/nieobecnosci") },
  { href: "#/raporty", label: "Raporty", icon: "chart", match: (p) => p.startsWith("/raporty") },
  { href: "#/ustawienia", label: "Ustawienia", icon: "sliders", match: (p) => p.startsWith("/ustawienia") },
];

function path() {
  return (location.hash || "#/").slice(1) || "/";
}

function renderNav() {
  const p = path();
  replace(
    document.getElementById("nav"),
    NAV.map((n) =>
      h("a", { href: n.href, "aria-current": n.match(p) ? "page" : false }, icon(n.icon, "icon-lg"), h("span", { class: "nav-label" }, n.label))
    )
  );
  const me = ctx.me;
  if (!me) return;
  const role = me.rola === "KADRY" ? "Kadry" : me.czy_oceniajacy ? "Oceniający" : "Oceniany";
  replace(
    document.getElementById("nav-user"),
    avatar(me.pracownik.imie, me.pracownik.nazwisko),
    h("div", { class: "who" },
      h("div", { class: "who-name" }, `${me.pracownik.imie} ${me.pracownik.nazwisko}`),
      h("div", { class: "who-role" }, me.pracownik.stanowisko ? `${role} – ${me.pracownik.stanowisko}` : role),
      h("div", { class: "who-office" }, me.urzad))
  );
}

function aiChip() {
  const m = ctx.meta;
  let state = "on";
  let text = "Asystent AI: model lokalny";
  if (!m || m.tryb_ai === "OFF") {
    state = "off";
    text = "Asystent AI: wyłączony (szablony)";
  } else if (m.tryb_ai === "API") {
    text = "Asystent AI: usługa zewnętrzna";
  } else if (!m.funkcje_ai?.model_dostepny) {
    state = "down";
    text = "Asystent AI: model lokalny niedostępny – szablony";
  }
  return h("span", { class: "chip-ai", "data-state": state, title: "Tryb pracy asystenta" },
    h("span", { class: "dot", "aria-hidden": "true" }), text);
}

function renderTopbar() {
  const years = ["all", "2026", "2027"];
  const yearSel = h("select", { id: "year", onchange: (e) => { ctx.year = e.target.value; route(); } },
    years.map((y) => h("option", { value: y, selected: ctx.year === y }, y === "all" ? "Wszystkie" : y)));
  const userSel = h("select", {
    id: "demo-user",
    onchange: async (e) => {
      setCurrentUserId(e.target.value);
      await boot();
      location.hash = "#/";
    },
  }, ctx.users.map((u) => h("option", { value: u.id, selected: String(u.id) === currentUserId(), title: u.opis }, `${u.nazwa} – ${u.opis.split(" – ")[0]}`)));

  const shift = (days) => async () => {
    const r = await api.clock({ przesun_dni: days });
    toast(`Zegar demo: ${fmtDate(r.dzis)}. Przypomnienia do wysłania: ${r.nowe_powiadomienia}.`);
    ctx.meta = await api.meta();
    renderTopbar();
    route();
  };
  replace(
    document.getElementById("topbar"),
    h("label", {}, "Rok oceny", yearSel),
    aiChip(),
    h("span", { class: "spacer" }),
    h("div", { class: "demo-tools", "aria-label": "Narzędzia demonstracyjne" },
      h("span", { class: "demo-tag" }, "Demo"),
      h("span", { class: "small muted", title: "Data z zegara serwera, nie z przeglądarki" },
        icon("calendar"), " ", ctx.meta ? fmtDate(ctx.meta.dzis) : "–"),
      h("button", { class: "btn btn-sm", type: "button", onclick: shift(7), title: "Przewiń czas o tydzień" },
        icon("forward"), "+7 dni"),
      h("button", { class: "btn btn-sm", type: "button", onclick: shift(30), title: "Przewiń czas o 30 dni" }, "+30 dni"),
      h("button", {
        class: "btn btn-sm", type: "button", title: "Przywróć dane przykładowe",
        onclick: async () => { await api.reset(); await boot(); toast("Przywrócono dane przykładowe."); },
      }, icon("reset"), h("span", { class: "sr-only" }, "Przywróć dane przykładowe")),
      h("label", {}, h("span", { class: "sr-only" }, "Zalogowany jako"), userSel))
  );
}

async function route() {
  renderNav();
  const view = document.getElementById("view");
  const p = path();
  replace(view, loading());
  try {
    const m = p.match(/^\/ocena\/(\d+)/);
    if (m) await renderEvaluation(view, Number(m[1]), ctx);
    else if (p.startsWith("/terminy")) await renderDeadlines(view, ctx);
    else if (p.startsWith("/nieobecnosci")) await renderAbsences(view, ctx, Number(p.split("/")[2]) || null);
    else if (p.startsWith("/pracownicy")) renderPlaceholder(view, "Pracownicy", "Lista pracowników z danymi kadrowymi i historią ocen.");
    else if (p.startsWith("/raporty")) renderPlaceholder(view, "Raporty", "Zestawienia dla kadr i dyrektora generalnego.");
    else if (p.startsWith("/ustawienia")) renderPlaceholder(view, "Ustawienia", "Konfiguracja urzędu, terminów przypomnień i asystenta.");
    else await renderOverview(view, ctx);
  } catch (e) {
    replace(view, h("div", { class: "card card-pad notice notice-bad" }, icon("alert"), e.message || String(e)));
  }
  view.focus({ preventScroll: true });
}

async function boot() {
  if (!ctx.users.length) ctx.users = await api.users();
  // default identity; also replaces an id remembered from an older version that the server no longer knows
  if (!ctx.users.some((u) => String(u.id) === currentUserId())) {
    setCurrentUserId(ctx.users.find((u) => u.nazwa === "Henryk Pryncypał")?.id ?? ctx.users[0].id);
  }
  [ctx.me, ctx.meta] = await Promise.all([api.me(), api.meta()]);
  renderTopbar();
  await route();
}

document.getElementById("brand-icon").append(icon("landmark", "icon-lg"));
window.addEventListener("hashchange", route);
boot().catch((e) => {
  replace(document.getElementById("view"),
    h("div", { class: "card card-pad notice notice-bad" }, icon("alert"), `Nie udało się uruchomić aplikacji: ${e.message}`));
});

export { route };
