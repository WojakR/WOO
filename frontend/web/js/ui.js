// Small DOM helpers. Data is always inserted as text (never innerHTML) – safe for notes and AI output.
import { icon } from "./icons.js";

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v === null || v === undefined) continue;
    if (k === "class") el.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, String(v));
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}

export function replace(el, ...children) {
  el.replaceChildren();
  append(el, children);
  return el;
}

export { icon };

export const MONTHS = ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca", "sierpnia",
  "września", "października", "listopada", "grudnia"];

export function parseDate(iso) {
  if (!iso) return null;
  const [y, m, d] = String(iso).slice(0, 10).split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

export function fmtDate(iso) {
  const d = parseDate(iso);
  if (!d) return "–";
  return `${String(d.getUTCDate()).padStart(2, "0")}.${String(d.getUTCMonth() + 1).padStart(2, "0")}.${d.getUTCFullYear()}`;
}

export function daysBetween(fromIso, toIso) {
  return Math.round((parseDate(toIso) - parseDate(fromIso)) / 86400000);
}

export function daysWord(n) {
  const a = Math.abs(n);
  return a === 1 ? "dzień" : "dni";
}

/** "zostało 18 dni" / "dziś" / "po terminie 3 dni" */
export function daysLeftText(days) {
  if (days === null || days === undefined) return "";
  if (days === 0) return "termin dziś";
  if (days < 0) return `po terminie ${-days} ${daysWord(days)}`;
  return `zostało ${days} ${daysWord(days)}`;
}

/** Urgency from days left; thresholds match the server's dashboard (≤ 7 pilne, ≤ 30 wkrótce). */
export function urgency(days) {
  if (days === null || days === undefined) return "OK";
  if (days < 0) return "PO_TERMINIE";
  if (days <= 7) return "PILNE";
  if (days <= 30) return "WKROTCE";
  return "OK";
}

export function deadlineBadge(days, { prefix = "" } = {}) {
  const u = urgency(days);
  const cls = u === "PO_TERMINIE" ? "badge-bad" : u === "OK" ? "badge-idle" : "badge-warn";
  const ic = u === "PO_TERMINIE" ? "alert" : "clock";
  return h("span", { class: `badge ${cls}` }, icon(ic), prefix + daysLeftText(days));
}

export function initials(first, last) {
  return `${(first || "").charAt(0)}${(last || "").charAt(0)}`.toUpperCase();
}

export function avatar(first, last, cls = "") {
  return h("span", { class: `avatar ${cls}`, "aria-hidden": "true" }, initials(first, last));
}

export function fmtNumber(x, digits = 2) {
  if (x === null || x === undefined) return "–";
  return Number(x).toLocaleString("pl-PL", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function toast(message, kind = "") {
  const area = document.getElementById("toasts");
  const t = h("div", { class: `toast ${kind === "bad" ? "toast-bad" : ""}` }, message);
  area.append(t);
  setTimeout(() => t.remove(), 5000);
}

export function loading(text = "Wczytywanie…") {
  return h("div", { class: "loading" }, h("span", { class: "spinner", "aria-hidden": "true" }), text);
}
