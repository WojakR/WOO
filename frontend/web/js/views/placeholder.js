import { h, icon, replace } from "../ui.js";

export function renderPlaceholder(view, title, description) {
  replace(view,
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, title), h("p", {}, description))),
    h("div", { class: "card card-pad notice notice-info" }, icon("info"),
      "Ten widok nie jest jeszcze dostępny w wersji demonstracyjnej. Przejdź do „Moje oceny”."));
}
