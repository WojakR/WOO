"""Shared UI pieces: styles, badges, stepper, cards, date formatting."""
from __future__ import annotations

from datetime import date
from html import escape

import streamlit as st

from frontend.demo_state import DONE, STAGES, DemoState

CSS = """
<style>
:root { --ink:#1f2328; --muted:#59636e; --line:#d1d9e0; --blue:#0b57d0; --blue-bg:#e8f0fe;
        --green:#1a7f37; --green-bg:#e6f4ea; --amber:#9a6700; --amber-bg:#fff8c5;
        --red:#b42318; --red-bg:#fdecea; --violet:#6f42c1; --violet-bg:#f1eafe; --grey-bg:#f6f8fa;
        --surface:#ffffff; }
@media (prefers-color-scheme: dark) {
  :root { --ink:#e6edf3; --muted:#9198a1; --line:#3d444d; --blue:#79b8ff; --blue-bg:rgba(56,139,253,.16);
          --green:#56d364; --green-bg:rgba(46,160,67,.16); --amber:#e3b341; --amber-bg:rgba(187,128,9,.18);
          --red:#ff7b72; --red-bg:rgba(248,81,73,.16); --violet:#d2a8ff; --violet-bg:rgba(163,113,247,.18);
          --grey-bg:rgba(110,118,129,.14); --surface:transparent; }
}
.block-container { padding-top: 3.6rem; max-width: 1400px; }
/* toasts (bottom-right notifications): bigger and easier to notice */
div[data-testid="stToast"] { min-width: 380px; padding: 14px 18px; font-size: 1.05rem;
                             border-left: 5px solid var(--blue); box-shadow: 0 6px 24px rgba(0,0,0,.25); }
div[data-testid="stToast"] p { font-size: 1.05rem; }
/* link-like buttons (schedule, notifications, names, column headers): left-aligned */
button[data-testid="stBaseButton-tertiary"] { justify-content: flex-start; text-align: left; }
button[data-testid="stBaseButton-tertiary"] div, button[data-testid="stBaseButton-tertiary"] p { text-align: left; justify-content: flex-start; }
.app-title { font-size: 1.35rem; font-weight: 700; margin: 0; line-height: 1.2; }
.app-sub { color: var(--muted); font-size: .85rem; margin: 0; }
.badge { display:inline-block; padding: 1px 8px; border-radius: 999px; font-size: .75rem; font-weight: 600;
         border: 1px solid transparent; white-space: nowrap; }
.b-blue { color: var(--blue); background: var(--blue-bg); }
.b-green { color: var(--green); background: var(--green-bg); }
.b-amber { color: var(--amber); background: var(--amber-bg); }
.b-red { color: var(--red); background: var(--red-bg); }
.b-violet { color: var(--violet); background: var(--violet-bg); }
.b-grey { color: var(--muted); background: var(--grey-bg); border-color: var(--line); }
.step { border: 1px solid var(--line); border-radius: 10px; padding: 8px 10px; min-height: 66px; background: var(--surface); }
.step.sel { outline: 2px solid var(--blue); outline-offset: -1px; }
.step .n { font-size: .7rem; color: var(--muted); font-weight: 600; letter-spacing: .02em; }
.step .t { font-weight: 650; font-size: .9rem; line-height: 1.2; }
.step.done { background: var(--green-bg); border-color: var(--green); }
.step.active { background: var(--blue-bg); border-color: var(--blue); }
.step.waiting { background: var(--amber-bg); border-color: var(--amber); }
.deadline { border-left: 4px solid var(--blue); background: var(--grey-bg); padding: 6px 12px; border-radius: 6px;
            font-size: .9rem; margin: 4px 0 10px; }
.deadline.warn { border-color: #d4a72c; background: var(--amber-bg); }
.deadline.late { border-color: var(--red); background: var(--red-bg); }
.card { border: 1px solid var(--line); border-radius: 10px; padding: 10px 12px; margin-bottom: 8px; background: var(--surface); }
.card h4 { margin: 0 0 4px; font-size: .95rem; }
.card p, .card li { font-size: .86rem; margin: 2px 0; }
.card ul { padding-left: 18px; margin: 4px 0; }
.card.c-amber { border-left: 4px solid #d4a72c; }
.card.c-green { border-left: 4px solid var(--green); }
.card.c-red { border-left: 4px solid var(--red); }
.card.c-blue { border-left: 4px solid var(--blue); }
.kv { display:grid; grid-template-columns: auto 1fr; gap: 2px 10px; font-size: .86rem; }
.kv .k { color: var(--muted); }
.lock { color: var(--muted); font-size: .8rem; }
.note { border-bottom: 1px solid var(--line); padding: 6px 0; font-size: .88rem; }
.note .d { color: var(--muted); font-size: .75rem; }
.result { border-radius: 10px; padding: 10px 14px; margin: 6px 0; font-size: .95rem; }
.result.pos { background: var(--green-bg); color: var(--green); }
.result.neg { background: var(--red-bg); color: var(--red); }
.result.pending { background: var(--grey-bg); color: var(--muted); }
div[data-testid="stVerticalBlockBorderWrapper"] { border-radius: 10px; }
</style>
"""

STATE_ICON = {"done": "✔", "active": "●", "waiting": "⏳", "todo": "○"}
SOURCE_STYLE = {"AI": ("b-violet", "✨ AI"), "SZABLON": ("b-grey", "SZABLON"), "REGULY": ("b-blue", "REGUŁY")}
SENTIMENT = {"POZYTYWNY": ("b-green", "+ pozytywna"), "NEUTRALNY": ("b-grey", "neutralna"),
             "NEGATYWNY": ("b-red", "− negatywna")}


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def fmt(d: date | None) -> str:
    return d.strftime("%d.%m.%Y") if d else "—"


def badge(text: str, cls: str = "b-grey") -> str:
    return f'<span class="badge {cls}">{escape(text)}</span>'


def source_badge(source: str) -> str:
    cls, label = SOURCE_STYLE.get(source, ("b-grey", source))
    return badge(label, cls)


def html(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


def days_text(days: int) -> str:
    if days < 0:
        return f"{-days} dni po terminie"
    if days == 0:
        return "dziś"
    return f"za {days} dni"


def urgency(days: int | None) -> str:
    if days is None:
        return "⚪"
    if days < 0:
        return "🔴"
    if days <= 30:
        return "🟡"
    return "🟢"


def deadline_bar(label: str, due: date | None, today: date) -> None:
    if due is None:
        html(f'<div class="deadline">{escape(label)}</div>')
        return
    left = (due - today).days
    cls = "late" if left < 0 else "warn" if left <= 30 else ""
    html(f'<div class="deadline {cls}"><b>{escape(label)}:</b> {fmt(due)} · {days_text(left)}</div>')


def stage_label(stage: int) -> str:
    return "Zakończona" if stage == DONE else f"{stage} · {STAGES[stage - 1]}"


def stepper(state: DemoState, cycle, selected: int, key: str) -> int:
    """Clickable process steps; returns the stage the user selected."""
    cols = st.columns(len(STAGES))
    for i, (col, name) in enumerate(zip(cols, STAGES), start=1):
        st_state, st_label = state.stage_status(cycle, i)
        with col:
            sel = " sel" if i == selected else ""
            html(f'<div class="step {st_state}{sel}"><div class="n">ETAP {i}</div><div class="t">{escape(name)}</div>'
                 f'<div class="n">{STATE_ICON[st_state]} {escape(st_label)}</div></div>')
            if st.button("Pokaż" if i != selected else "Wybrany", key=f"{key}_{i}", use_container_width=True,
                         type="primary" if i == selected else "secondary", disabled=i == selected):
                selected = i
                st.session_state[key] = i
                st.rerun()
    return selected


def mini_stepper(state: DemoState, cycle) -> None:
    parts = []
    for i, name in enumerate(STAGES, start=1):
        st_state, _ = state.stage_status(cycle, i)
        cls = {"done": "b-green", "active": "b-blue", "waiting": "b-amber", "todo": "b-grey"}[st_state]
        parts.append(badge(f"{STATE_ICON[st_state]} {i}. {name}", cls))
    html(" ".join(parts))


def card(title: str, body: str, tone: str = "", extra: str = "") -> None:
    html(f'<div class="card {tone}"><h4>{escape(title)} {extra}</h4>{body}</div>')


def kv(rows: list[tuple[str, str]]) -> str:
    return '<div class="kv">' + "".join(
        f'<div class="k">{escape(k)}</div><div>{escape(v)}</div>' for k, v in rows) + "</div>"


def ul(items) -> str:
    items = [i for i in items if i]
    return "<ul>" + "".join(f"<li>{escape(str(i))}</li>" for i in items) + "</ul>" if items else ""


def show_problems(problems: list[str]) -> None:
    if problems:
        st.error("**Nie można zapisać:**\n" + "\n".join(f"- {p}" for p in problems))
