"""Shared UI pieces: styles, badges, stepper, cards, date formatting."""
from __future__ import annotations

from datetime import date
from html import escape

import streamlit as st

from frontend.process import DONE, STAGES, stage_date, stage_state, to_date

CSS = """
<style>
.block-container { padding: 1.6rem 2.5rem 2rem; max-width: 1800px; }
[data-testid="stHeader"] { height: 2.4rem !important; min-height: 2.4rem !important; background: transparent !important; }
[data-testid="stHeader"] [data-testid="stToolbar"] { top: 0 !important; }
@media (max-width: 900px) { .block-container { padding-left: 1rem; padding-right: 1rem; } }
/* toasts (bottom-right notifications): big, high-contrast, easy to notice */
/* notifications pop up top-right, under the bar – never over the HR partner button in the bottom-right corner */
div[data-testid="stToastContainer"] { top: 3rem !important; bottom: auto !important; right: 24px !important; }
/* the invisible style blocks injected at the top take no room (otherwise ~80 px of gaps above the content) */
[data-testid="stMain"] [data-testid="stElementContainer"]:has(style):not(:has(p, h1, h2, h3, h4, table, img, button)),
section[data-testid="stSidebar"] [data-testid="stElementContainer"]:has(iframe[height="1"]),
section[data-testid="stSidebar"] [data-testid="stElementContainer"]:has(style):not(:has(p, button, input)) { display: none !important; }
div[data-testid="stToast"] { min-width: 460px; max-width: 560px; padding: 18px 22px; font-size: 1.2rem;
                             border: 2px solid var(--blue); border-left: 8px solid var(--blue);
                             box-shadow: 0 10px 32px rgba(0,0,0,.35); }
div[data-testid="stToast"] p { font-size: 1.2rem; font-weight: 600; line-height: 1.4; }
/* no keyboard-shortcut hints ("Press Ctrl+Enter to apply") – every action has its own button */
[data-testid="InputInstructions"] { display: none !important; }
/* WCAG 2.4.7: always visible keyboard focus */
*:focus-visible { outline: 3px solid #f59e0b !important; outline-offset: 2px !important; }
/* partial scores 1/3/5/7/9: the selected point is coloured from red to green */
.st-key-scores button[role="radio"][aria-checked="true"] { color: #fff !important; font-weight: 700; }
.st-key-scores button[role="radio"][aria-checked="true"]:nth-of-type(1) { background: #c62828 !important; border-color: #c62828 !important; }
.st-key-scores button[role="radio"][aria-checked="true"]:nth-of-type(2) { background: #e8710a !important; border-color: #e8710a !important; }
.st-key-scores button[role="radio"][aria-checked="true"]:nth-of-type(3) { background: #1a73e8 !important; border-color: #1a73e8 !important; }
.st-key-scores button[role="radio"][aria-checked="true"]:nth-of-type(4) { background: #34a853 !important; border-color: #34a853 !important; }
.st-key-scores button[role="radio"][aria-checked="true"]:nth-of-type(5) { background: #137333 !important; border-color: #137333 !important; }
.st-key-scores button[role="radio"] p { font-size: 1.05rem; }
/* side menu: items left-aligned, a bit taller, like a classic navigation list */
section[data-testid="stSidebar"] .stButton button { justify-content: flex-start; min-height: 2.8rem; }
section[data-testid="stSidebar"] .stButton button div,
section[data-testid="stSidebar"] .stButton button p { justify-content: flex-start; text-align: left; font-weight: 600; }
/* loading: a spinner in the middle of the screen while the page works (shown after a short delay) */
.stApp[data-test-script-state="running"]::after {
  content: ""; position: fixed; top: 50%; left: 50%; width: 64px; height: 64px; margin: -32px 0 0 -32px;
  border: 7px solid rgba(127,127,127,.25); border-top-color: var(--blue); border-radius: 50%; z-index: 100000;
  opacity: 0; animation: aoo-spin .8s linear infinite, aoo-show .01s linear .35s forwards; pointer-events: none; }
@keyframes aoo-spin { to { transform: rotate(360deg); } }
@keyframes aoo-show { to { opacity: 1; } }
/* team list: the whole row opens the evaluation (an invisible full-size button over the row) */
[class*="st-key-row_"] { position: relative; }
[class*="st-key-row_"]:hover { background: var(--grey-bg); cursor: pointer; }
[class*="st-key-rowbtn_"] { position: absolute !important; inset: 0; z-index: 3; margin: 0 !important; width: auto !important; }
/* every wrapper between the row and the <button> must fill the row, or clicks land on an empty wrapper */
[class*="st-key-rowbtn_"] div, [class*="st-key-rowbtn_"] button { width: 100% !important; height: 100% !important; }
[class*="st-key-rowbtn_"] button { background: transparent !important; border: none !important; color: transparent !important;
                                   cursor: pointer; }
/* communication tips table (review meeting) */
.tips { width: 100%; border-collapse: collapse; margin: 4px 0 8px; font-size: .92rem; }
.tips th { text-align: left; padding: 8px 10px; border-bottom: 2px solid var(--line); color: var(--ink); }
.tips th:first-child { color: var(--red); } .tips th:last-child { color: var(--green); }
.tips td { padding: 8px 10px; border-bottom: 1px solid var(--line); vertical-align: top; width: 50%; }
.tips td:first-child { color: var(--muted); }
/* HR partner: floating round button, bottom-right, always in view */
.st-key-hrfab { position: fixed !important; right: 28px; bottom: 28px; z-index: 1000; width: auto !important; }
.st-key-hrfab button { width: 4.2rem; height: 4.2rem; border-radius: 50% !important; background: var(--navy) !important;
  border: 3px solid #ffffff !important; box-shadow: 0 6px 18px rgba(0,0,0,.35); }
.st-key-hrfab button p { color: #ffffff !important; font-size: 1.25rem; font-weight: 700; }
.st-key-hrfab button svg { display: none; }
[data-testid="stPopoverBody"] { max-width: min(460px, 92vw); }
/* ---- everything that comes from the assistant (AI, HR partner, suggestions) has ONE colour: violet ---- */
.ai-text, .ai-text p, .ai-text strong { color: var(--ai) !important; }
.badge.b-violet { color: var(--ai) !important; background: var(--ai-bg) !important; border-color: var(--ai) !important; }
/* AI switch in the top bar and assistant switches in settings */
.st-key-ai_on label p, .st-key-ai_on label span { color: var(--ai) !important; font-weight: 650; }
[class*="st-key-ai_on"] [data-testid="stCheckbox"] label:has(input:checked) > div:first-of-type,
.st-key-ai_on label:has(input:checked) > div:first-of-type,
[class*="st-key-office_ai"] label:has(input:checked) > div:first-of-type,
[class*="st-key-office_hr"] label:has(input:checked) > div:first-of-type,
[class*="st-key-my_hr"] label:has(input:checked) > div:first-of-type { background-color: var(--ai) !important; }
/* assistant buttons: drafts, accepting suggestions, HR partner decisions */
[class*="st-key-dr_"] button, [class*="st-key-acc_"] button, [class*="st-key-use_"] button,
[class*="st-key-edit_"] button, [class*="st-key-rej_draft"] button, [class*="st-key-hr_ok_"] button,
[class*="st-key-hr_no_"] button {
  border: 1.5px solid var(--ai) !important; color: var(--ai) !important; background: var(--ai-bg) !important; }
[class*="st-key-dr_"] button p, [class*="st-key-acc_"] button p, [class*="st-key-use_"] button p,
[class*="st-key-edit_"] button p, [class*="st-key-rej_draft"] button p, [class*="st-key-hr_ok_"] button p,
[class*="st-key-hr_no_"] button p { color: var(--ai) !important; }
[class*="st-key-use_"] button, [class*="st-key-hr_ok_"] button { background: var(--ai) !important; }
[class*="st-key-use_"] button p, [class*="st-key-hr_ok_"] button p { color: #ffffff !important; }
/* framed assistant content: draft proposal, conversation tips, HR partner panel */
[class*="st-key-aibox"] { border: 2px solid var(--ai) !important; border-radius: 10px; background: var(--ai-bg) !important; }
[class*="st-key-aiprep"] [data-testid="stExpander"] details { border-color: var(--ai) !important; }
[class*="st-key-aiprep"] [data-testid="stExpander"] summary p { color: var(--ai) !important; font-weight: 650; }
/* assistant tips (conversation preparation): violet window like the HR partner */
html body [class*="st-key-aiprep"] [data-testid="stExpander"] > details { background: var(--ai-bg) !important; border: 2px solid var(--ai) !important; }
html:not([data-aoo-theme="dark"]) [class*="st-key-aiprep"] [data-testid="stExpander"] details { background: #ece3fb !important; }
html:not([data-aoo-theme="dark"]) [class*="st-key-aiprep"] [data-testid="stVerticalBlock"][class*="st-key-"]:not([class*="st-key-aiprep"]),
html:not([data-aoo-theme="dark"]) [class*="st-key-aiprep"] [data-testid="stLayoutWrapper"] > [data-testid="stVerticalBlock"] { background: #f6f1fe; }
/* HR partner window: light violet background in the light theme */
html:not([data-aoo-theme="dark"]) [data-testid="stPopoverBody"]:has(.st-key-hrpanel) { background: #ece3fb !important; }
html:not([data-aoo-theme="dark"]) .st-key-hrpanel { background: #f6f1fe !important; border-color: #cdb8f4 !important; }
/* HR partner: violet round button with a robot, bottom-right */
.st-key-hrfab button { background: var(--ai) !important; display: flex !important; align-items: center;
  justify-content: center; padding: 0 !important; }
.st-key-hrfab button > div { justify-content: center !important; width: 100%; padding: 0 !important; margin: 0 !important; }
.st-key-hrfab button > div > div:has([data-testid="stIconMaterial"]) { display: none !important; }
.st-key-hrfab button > div > div:first-child { width: 100% !important; justify-content: center !important; }
.st-key-hrfab button p { font-size: 2.6rem !important; line-height: 1 !important; margin: 0 !important; text-align: center; }
/* side menu: while the menu is rebuilt, the previous "current page" item is not highlighted any more
   (otherwise two items look selected for a moment) */
section[data-testid="stSidebar"] [data-stale="true"] button[data-testid="stBaseButton-primary"] {
  background: transparent !important; box-shadow: none !important; }
section[data-testid="stSidebar"] [data-stale="true"] button[data-testid="stBaseButton-primary"] p {
  color: var(--band-ink) !important; }
/* overview: stat cards */
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin: 8px 0 12px; }
.stat .v { font-size: 2rem; font-weight: 700; line-height: 1.2; }
/* overview: stage bar */
.funnel-bar { display: flex; height: 18px; border-radius: 6px; overflow: hidden; margin: 8px 0; background: var(--grey-bg); }
.funnel-bar span { display: block; height: 100%; }
.funnel-legend { display: flex; flex-wrap: wrap; gap: 6px 18px; font-size: .85rem; }
.funnel-item .sw { display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 6px; }
/* evaluation: person card */
.person-card { display: flex; gap: 14px; align-items: flex-start; }
.avatar { flex: 0 0 auto; width: 52px; height: 52px; border-radius: 50%; background: var(--blue-bg); color: var(--blue);
          display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 1.1rem; }
/* ---- identity: navy side band, navy primary actions (instead of Streamlit's default red) ---- */
section[data-testid="stSidebar"] { background: var(--band) !important; }
/* Material Symbols inside our own HTML (badges, notes, titles) – the font Streamlit already loads */
.msi { font-family: "Material Symbols Rounded"; font-weight: normal; font-style: normal; font-size: 1.15em;
  line-height: 1; vertical-align: -0.18em; display: inline-block; letter-spacing: normal; text-transform: none;
  white-space: nowrap; direction: ltr; -webkit-font-feature-settings: "liga"; font-feature-settings: "liga"; }
/* side menu tiles: icon + label */
section[data-testid="stSidebar"] [class*="st-key-nav_"] [data-testid="stIconMaterial"] { font-size: 1.3rem; margin-right: .35rem; }
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] b,
section[data-testid="stSidebar"] .app-title, section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] [data-testid="stExpander"] summary { color: var(--band-ink) !important; }
section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p { color: var(--band-muted) !important; }
section[data-testid="stSidebar"] hr { border-color: var(--band-line) !important; }
section[data-testid="stSidebar"] [data-testid="stExpander"] details { border-color: var(--band-line) !important;
  background: rgba(255,255,255,.04); }
section[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"] svg,
section[data-testid="stSidebar"] [data-testid="stExpander"] svg { color: var(--band-ink) !important; fill: var(--band-ink); }
/* the side panel can always be folded: the « button is shown all the time, not only on hover */
[data-testid="stSidebarCollapseButton"] { visibility: visible !important; opacity: 1 !important; }
[data-testid="stSidebarCollapseButton"] button { background: #ffffff !important; border: none !important;
  border-radius: 8px; width: 2.4rem; height: 2.4rem; box-shadow: 0 1px 4px rgba(0,0,0,.35); }
[data-testid="stSidebarCollapseButton"] button svg, [data-testid="stSidebarCollapseButton"] button span {
  color: #1c3460 !important; fill: #1c3460 !important; }
[data-testid="stExpandSidebarButton"] { background: #1c3460 !important; border-radius: 8px; width: 2.4rem; height: 2.4rem; }
[data-testid="stExpandSidebarButton"] svg, [data-testid="stExpandSidebarButton"] span { color: #ffffff !important;
  fill: #ffffff !important; }
/* Streamlit's own "Deploy" button is not part of the app */
[data-testid="stAppDeployButton"] { display: none !important; }
/* tiles and framed sections: clearly separated from the background (only framed blocks have a border width) */
[data-testid="stMain"] [data-testid="stVerticalBlock"], [data-testid="stMain"] [data-testid="stExpander"] details,
[data-testid="stMain"] .card, [data-testid="stMain"] [data-testid="stPopoverButton"] { border-color: var(--tile-line) !important; }
[data-testid="stMain"] [data-testid="stExpander"] details, [data-testid="stMain"] .card { border-width: 1.5px !important; }
[data-testid="stMain"] [class*="st-key-row_"] { border: 1.5px solid var(--tile-line) !important; background: var(--tile-bg); }
/* footnotes: a short "*" explanation under a field instead of long inline hints */
.footnote { font-size: .8rem; color: var(--muted); margin: 2px 0 10px; }
/* menu items: quiet list on the band; the current page is white with navy text and a bar on the left */
section[data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"] {
  background: transparent !important; border: 1px solid transparent !important; color: var(--band-ink) !important; }
section[data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"]:hover {
  background: rgba(255,255,255,.08) !important; border-color: var(--band-line) !important; }
section[data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"] p { color: var(--band-ink) !important; }
section[data-testid="stSidebar"] button[data-testid="stBaseButton-primary"] {
  background: #ffffff !important; border: none !important; box-shadow: inset 5px 0 0 #c9a227 !important; }
section[data-testid="stSidebar"] button[data-testid="stBaseButton-primary"] p { color: #1c3460 !important; }
/* demo / accessibility expanders keep readable inputs on the band */
section[data-testid="stSidebar"] [data-testid="stExpander"] button[data-testid="stBaseButton-secondary"] {
  border-color: var(--band-line) !important; }
/* primary actions in the content: navy */
[data-testid="stPopoverBody"] button[data-testid="stBaseButton-primary"],
[data-testid="stMain"] button[data-testid="stBaseButton-primary"], [data-testid="stMain"] button[kind="primaryFormSubmit"],
[data-testid="stMain"] button[data-testid="stBaseButton-primaryFormSubmit"] {
  background: var(--navy) !important; border-color: var(--navy) !important; color: var(--navy-ink) !important; }
[data-testid="stMain"] button[data-testid="stBaseButton-primary"]:hover,
[data-testid="stMain"] button[data-testid="stBaseButton-primaryFormSubmit"]:hover { background: var(--navy-hover) !important; }
[data-testid="stPopoverBody"] button[data-testid="stBaseButton-primary"] p,
[data-testid="stMain"] button[data-testid="stBaseButton-primary"] p,
[data-testid="stMain"] button[data-testid="stBaseButton-primaryFormSubmit"] p { color: var(--navy-ink) !important; }
/* switches (e.g. Asystent AI) when on: navy instead of the default red */
[data-testid="stCheckbox"] label:has(input:checked) > div:first-of-type { background-color: var(--navy) !important; }
section[data-testid="stSidebar"] [data-testid="stCheckbox"] label:has(input:checked) > div:first-of-type {
  background-color: #c9a227 !important; }
/* headings: calm hierarchy, sentence case */
[data-testid="stMain"] h3 { font-weight: 650; letter-spacing: -0.005em; }
[data-testid="stMain"] h4 { font-weight: 650; color: var(--ink); }
.step.sel { outline: 2px solid var(--navy) !important; }
.deadline { border-left-color: var(--navy); }
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
.stage-sep { height: 4px; border-radius: 2px; background: var(--navy); opacity: .85; margin: 10px 0 14px; }
.stepper { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 1rem; margin-bottom: 6px; }
.step { border: 1px solid var(--line); border-radius: 10px; padding: 8px 10px; background: var(--surface);
        display: flex; flex-direction: column; box-sizing: border-box; min-width: 0; overflow-wrap: anywhere; }
.step .d { margin-top: auto !important; }
.step.sel { outline: 2px solid var(--blue); outline-offset: -1px; }
.step .n { font-size: .78rem; color: var(--muted); font-weight: 600; }
.step .num { width: 1.9rem; height: 1.9rem; border-radius: 50%; display: flex; align-items: center;
             justify-content: center; font-weight: 700; font-size: .9rem; border: 2px solid var(--line);
             color: var(--muted); background: var(--surface); margin-bottom: 6px; }
.step.done .num { background: var(--green); border-color: var(--green); color: #fff; }
.step.active .num { background: var(--navy); border-color: var(--navy); color: var(--navy-ink); }
.step.waiting .num { background: var(--amber); border-color: var(--amber); color: #fff; }
.step .t { font-weight: 650; font-size: .9rem; line-height: 1.2; }
.step { position: relative; }
.step .d { align-self: flex-start; font-size: .82rem; color: var(--ink); font-weight: 700; margin-top: 6px;
           padding: 2px 7px; border-radius: 6px; background: var(--date-bg); border: 1px solid var(--line); }
/* the line between steps: the process is one sequence */
.step:not(.last)::after { content: ""; position: absolute; top: 50%; right: calc(-1rem - 1px); width: calc(1rem + 1px);
                          height: 3px; background: var(--line); z-index: 0; }
.step.done:not(.last)::after { background: var(--green); }
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

STATE_ICON = {"done": "✔", "active": "●", "waiting": ":material/hourglass_top:", "todo": "○"}
SOURCE_STYLE = {"AI": ("b-violet", ":material/auto_awesome: AI"), "SZABLON": ("b-violet", ":material/auto_awesome: SZABLON"), "REGULY": ("b-violet", ":material/auto_awesome: REGUŁY")}
SOURCE_TEXT = {
    "AI": "wygenerowane przez model językowy (AI) na podstawie danych, po pseudonimizacji",
    "SZABLON": "przygotowane z gotowego szablonu i danych oceny – bez udziału AI",
    "REGULY": "wyliczone z reguł (słowa kluczowe, terminy, notatki) – bez udziału AI",
}
FONT_SCALES = {"Standardowa": 1.2, "Duża": 1.4, "Bardzo duża": 1.6}
URGENCY = {"late": ("Po terminie", "b-red"), "soon": ("Wkrótce", "b-amber"),
           "ok": ("W terminie", "b-green"), "none": ("Zakończona", "b-grey")}

ACCESSIBILITY_CSS = """
<style>
html {{ font-size: {px}px; }}
{contrast}
</style>
"""
LIGHT_VARS = """--ink:#1f2328; --muted:#59636e; --line:#d1d9e0; --blue:#0b57d0; --blue-bg:#e8f0fe;
  --green:#1a7f37; --green-bg:#e6f4ea; --amber:#9a6700; --amber-bg:#fff8c5; --red:#b42318; --red-bg:#fdecea;
  --violet:#6d28d9; --violet-bg:#e6dafb; --ai:#6d28d9; --ai-bg:#e9defb; --grey-bg:#f3f5f8; --surface:#ffffff; --date-bg:#ffffff;
  --navy:#1c3460; --navy-hover:#142748; --navy-ink:#ffffff; --band:#1c3460; --band-ink:#ffffff;
  --band-muted:#c8d3e6; --band-line:rgba(255,255,255,.22); --tile-line:#b4bfcd; --tile-bg:#ffffff;"""
DARK_VARS = """--ink:#e6edf3; --muted:#9198a1; --line:#3d444d; --blue:#79b8ff; --blue-bg:rgba(56,139,253,.16);
  --green:#56d364; --green-bg:rgba(46,160,67,.16); --amber:#e3b341; --amber-bg:rgba(187,128,9,.18);
  --red:#ff7b72; --red-bg:rgba(248,81,73,.16); --violet:#c4a7ff; --violet-bg:rgba(163,113,247,.18); --ai:#c4a7ff; --ai-bg:rgba(163,113,247,.16);
  --grey-bg:rgba(110,118,129,.14); --surface:transparent; --date-bg:rgba(0,0,0,.35);
  --navy:#4a72c4; --navy-hover:#5c82d0; --navy-ink:#ffffff; --band:#13233f; --band-ink:#f2f5fa;
  --band-muted:#aebbd3; --band-line:rgba(255,255,255,.16); --tile-line:#4a5563; --tile-bg:rgba(255,255,255,.035);"""
# high contrast: secondary text as dark/bright as the main text, strong borders – explicit colours per theme
HC_LIGHT = "--ink:#000000; --muted:#1f2328; --line:#424a53; --blue:#0a3d91; --green:#0f5323; --red:#8a1c12; --amber:#6b4700;"
HC_DARK = "--ink:#ffffff; --muted:#f0f3f6; --line:#c9d1d9; --blue:#a5d6ff; --green:#7ee787; --red:#ffa198; --amber:#f2cc60;"
HIGH_CONTRAST = """
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p, .lock, .app-sub, .note .d, .step .n {
  color: var(--muted) !important; opacity: 1 !important; }
.badge { border: 1px solid currentColor !important; }
.card, .step, div[data-testid="stVerticalBlockBorderWrapper"] { border-width: 2px !important; }
a, button[data-testid="stBaseButton-tertiary"] p { text-decoration: underline; }
"""
SENTIMENT = {"POZYTYWNY": ("b-green", "+ pozytywna"), "NEUTRALNY": ("b-grey", "neutralna"),
             "NEGATYWNY": ("b-red", "− negatywna")}


def _theme_type() -> str | None:
    try:
        return st.context.theme.type  # "light" / "dark" – the theme the app really shows (not the OS setting)
    except Exception:  # noqa: BLE001 – older Streamlit or first load: fall back to the OS preference
        return None


HIDE_STALE = """<style>
/* page switch only: hide the previous page – stale elements, and frames/columns left with only stale content
   (otherwise their empty borders show up as doubled tiles for a moment) */
[data-testid="stMain"] [data-stale="true"] { display: none !important; }
[data-testid="stMain"] [data-testid="stLayoutWrapper"]:has([data-stale="true"]):not(:has([data-stale="false"])),
[data-testid="stMain"] [data-testid="stHorizontalBlock"]:has([data-stale="true"]):not(:has([data-stale="false"])) {
  display: none !important; }
</style>"""


def inject_css(font_scale: float = 1.0, high_contrast: bool = False, page_switch: bool = False) -> None:
    """Base styles + accessibility settings (WCAG 2.1: 1.4.4 resize text, 1.4.3/1.4.6 contrast).
    Colours follow the app's own theme, so light text never lands on a light background."""
    theme = _theme_type()
    light = LIGHT_VARS + (HC_LIGHT if high_contrast else "")
    dark = DARK_VARS + (HC_DARK if high_contrast else "")
    if theme == "dark":
        tokens = f":root {{ {dark} }}"
    elif theme == "light":
        tokens = f":root {{ {light} }}"
    else:
        tokens = f":root {{ {light} }} @media (prefers-color-scheme: dark) {{ :root {{ {dark} }} }}"
    # the live theme (set by theme_watcher()) wins over the guess above – also right after a theme change
    tokens += f" :root[data-aoo-theme='light'] {{ {light} }} :root[data-aoo-theme='dark'] {{ {dark} }}"
    st.markdown(f"<style>{tokens}</style>", unsafe_allow_html=True)
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown(ACCESSIBILITY_CSS.format(px=round(17 * font_scale), contrast=HIGH_CONTRAST if high_contrast else ""),
                unsafe_allow_html=True)
    # always the same element at this position: with the rule on a page switch, empty otherwise
    st.markdown(HIDE_STALE if page_switch else "<style></style>", unsafe_allow_html=True)


def source_note(source: str) -> str:
    """Badge + plain-language explanation of where a suggestion comes from."""
    return f"{source_badge(source)} <span class='lock'>Źródło: {escape(SOURCE_TEXT.get(source, source))}.</span>"


def fmt(d) -> str:
    d = to_date(d)
    return d.strftime("%d.%m.%Y") if d else "—"


_ICON = __import__("re").compile(r":material/([a-z0-9_]+):")


def icons(markup: str) -> str:
    """:material/name: inside raw HTML is not drawn by Streamlit – turn it into a Material Symbols span."""
    return _ICON.sub(r'<span class="msi" aria-hidden="true">\1</span>', markup)


def badge(text: str, cls: str = "b-grey") -> str:
    return f'<span class="badge {cls}">{icons(escape(text))}</span>'


def source_badge(source: str) -> str:
    cls, label = SOURCE_STYLE.get(source, ("b-grey", source))
    return f'<span class="badge {cls}" title="{escape(SOURCE_TEXT.get(source, ""))}">{icons(escape(label))}</span>'


def nav_highlight(key: str) -> None:
    """Highlight the current side-menu tile (white tile, navy text) without changing the button itself."""
    sel = f"section[data-testid='stSidebar'] [data-testid='stSidebarUserContent'] .st-key-{key} button"
    st.markdown(f"<style>{sel}, {sel}:hover {{ background: #ffffff !important; border-color: #ffffff !important; }} "
                f"{sel} p, {sel} span {{ color: #1c3460 !important; }}</style>", unsafe_allow_html=True)


def html(markup: str) -> None:
    st.markdown(icons(markup), unsafe_allow_html=True)


def days_text(days: int) -> str:
    if days < 0:
        return f"{-days} dni po terminie"
    if days == 0:
        return "dziś"
    return f"za {days} dni"


def urgency(days: int | None) -> str:
    """Key of URGENCY: late / soon / ok / none."""
    if days is None:
        return "none"
    if days < 0:
        return "late"
    if days <= 30:
        return "soon"
    return "ok"


def urgency_badge(key: str) -> str:
    label, cls = URGENCY[key]
    return badge(label, cls)


def deadline_bar(label: str, due, today) -> None:
    due, today = to_date(due), to_date(today)
    if due is None:
        html(f'<div class="deadline">{escape(label)}</div>')
        return
    left = (due - today).days
    cls = "late" if left < 0 else "warn" if left <= 30 else ""
    html(f'<div class="deadline {cls}"><b>{escape(label)}:</b> {fmt(due)} · {days_text(left)}</div>')


def stage_label(stage: int) -> str:
    return "Zakończona" if stage == DONE else f"{stage} · {STAGES[stage - 1]}"


def stepper(ev: dict, selected: int, key: str) -> int:
    """Process steps with dates from the server, drawn as one grid so every box has the same height;
    the buttons below select the stage to show."""
    boxes = []
    for i, name in enumerate(STAGES, start=1):
        st_state, st_label = stage_state(ev, i)
        sel = " sel" if i == selected else ""
        last = " last" if i == len(STAGES) else ""
        when = stage_date(ev, i)
        num = "✓" if st_state == "done" else str(i)
        boxes.append(f'<div class="step {st_state}{sel}{last}"><div class="num" aria-label="Etap {i}">{num}</div>'
                     f'<div class="t">{escape(name)}</div><div class="n">{escape(st_label)}</div>'
                     + (f'<div class="d">📅 {escape(when)}</div>' if when else "") + "</div>")
    html('<div class="stepper">' + "".join(boxes) + "</div>")
    for i, col in enumerate(st.columns(len(STAGES)), start=1):
        if col.button("Pokaż" if i != selected else "Wybrany", key=f"{key}_{i}", use_container_width=True,
                      type="primary" if i == selected else "secondary", disabled=i == selected):
            st.session_state[key] = i
            st.rerun()
    html('<div class="stage-sep" role="separator"></div>')
    return selected


def mini_stepper(ev: dict) -> None:
    parts = []
    for i, name in enumerate(STAGES, start=1):
        st_state, _ = stage_state(ev, i)
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


def api_error(e) -> None:
    """Show an ApiError (komunikat + walidacje) from the server."""
    show_problems(getattr(e, "messages", None) or [str(e)])


def show_problems(problems: list[str]) -> None:
    if problems:
        st.error("**Nie można zapisać:**\n" + "\n".join(f"- {p}" for p in problems))


def footnote(text: str, mark: str = "*") -> None:
    """Short explanation under a field, referenced by an asterisk in its label."""
    html(f'<p class="footnote">{escape(mark)} {escape(text)}</p>')


THEME_WATCHER = r"""
<script>
// Marks the app page with data-aoo-theme="light" / "dark" from the real background colour of the app and keeps it
// up to date, so the app's own colours switch together with Streamlit's theme (Settings -> Theme) at once.
// The watcher is installed once into the page itself (not this helper frame, which Streamlit may rebuild).
(function () {
  const doc = window.parent.document;
  if (doc.getElementById('aoo-theme-watcher')) return;
  const s = doc.createElement('script');
  s.id = 'aoo-theme-watcher';
  s.textContent = `(function () {
    function update() {
      const app = document.querySelector('.stApp');
      if (!app) return;
      const bg = getComputedStyle(app).backgroundColor;
      const m = bg.slice(bg.indexOf('(') + 1, bg.indexOf(')')).split(',').map(Number);
      if (m.length < 3 || m.some(isNaN)) return;
      const lum = 0.2126 * m[0] + 0.7152 * m[1] + 0.0722 * m[2];
      const theme = lum < 128 ? 'dark' : 'light';
      if (document.documentElement.dataset.aooTheme !== theme) document.documentElement.dataset.aooTheme = theme;
    }
    update();
    setInterval(update, 400);
  })();`;
  doc.head.appendChild(s);
})();
</script>
"""


def theme_watcher() -> None:
    """Zero-height helper (same-origin iframe) that keeps data-aoo-theme on the page in step with the theme."""
    st.iframe(THEME_WATCHER, height=1)
