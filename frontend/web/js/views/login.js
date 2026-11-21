// Login screen (AUTH_MODE=session). The password goes only to POST /api/auth/login; the session is an HttpOnly cookie.
import { api } from "../api.js";
import { h, icon, replace } from "../ui.js";

export function renderLogin(view, onDone) {
  const err = h("div", { class: "notice notice-bad", role: "alert", hidden: true });
  const login = h("input", { type: "text", name: "login", autocomplete: "username", required: true });
  const pass = h("input", { type: "password", name: "haslo", autocomplete: "current-password", required: true });
  const btn = h("button", { class: "btn btn-primary", type: "submit" }, "Zaloguj się");
  const form = h("form", {
    onsubmit: async (e) => {
      e.preventDefault();
      btn.disabled = true;
      err.hidden = true;
      try {
        await api.login(login.value, pass.value);
        pass.value = "";
        await onDone();
      } catch (ex) {
        replace(err, icon("alert"), ex.message);
        err.hidden = false;
      } finally {
        btn.disabled = false;
      }
    },
  },
  h("label", {}, "Login", login),
  h("label", {}, "Hasło", pass),
  err,
  btn);
  replace(view, h("div", { class: "login-wrap" },
    h("section", { class: "card card-pad login-card", "aria-labelledby": "login-title" },
      h("h1", { id: "login-title" }, "Logowanie"),
      h("p", { class: "muted small" }, "Zaloguj się kontem nadanym przez dział kadr."),
      form)));
  login.focus();
}
