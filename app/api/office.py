"""Office settings the administrator (HR, `X-User-Id: kadry`) changes in the app – kept in the database:

- requirements of the regulation (terms, limit of additional criteria) – when the law is amended,
- who sees whose evaluations (whole subtree or direct reports only),
- the "off switch" of the AI assistant and of the virtual HR partner, office-wide; everyone can also turn
  them off for themselves (GET/PUT /api/me/asystent). With AI off every feature uses its no-AI version.
"""
from __future__ import annotations

import dataclasses

from fastapi import APIRouter, Depends, Header

from app.domain.access import VisibilityScope
from app.domain.errors import NotAuthorized
from app.infrastructure import regulations

from . import schemas as s
from .access import actor as _actor
from .state import HR, DemoState, RuleChangeRecord, get_state

router = APIRouter(prefix="/api", tags=["ustawienia"])


def _require_admin(who: str, what: str) -> None:
    if who != HR:
        raise NotAuthorized(f"{what} zmienia administrator (dział kadr).")


# ---------------------------------------------------------------- requirements of the regulation

def _rules_out(st: DemoState, who: str) -> s.RegulyOut:
    default = regulations.defaults()
    current = {**default, **st.rule_overrides}
    return s.RegulyOut(
        parametry=[s.RegulaOut(klucz=r.key, nazwa=r.label, wartosc=current[r.key], domyslna=default[r.key],
                               jednostka=r.unit, podstawa=r.basis, min=r.low, max=r.high)
                   for r in regulations.EDITABLE if r.key in current],
        wymagania=[s.WymaganieOut(tytul=t, tresc=x, podstawa=b)
                   for t, x, b in regulations.requirements(st.evaluations.rules)],
        zmiany=[s.ZmianaRegulyOut(klucz=c.key, nazwa=regulations.BY_KEY[c.key].label, stara=c.old, nowa=c.new,
                                  podstawa_zmiany=c.basis, kto="Dział kadr" if c.by == HR else c.by, kiedy=c.on)
                for c in reversed(st.rule_changes) if c.key in regulations.BY_KEY],
        zmienione=any(current[k] != default[k] for k in default),
        moze_edytowac=who == HR,
    )


@router.get("/ustawienia/reguly", response_model=s.RegulyOut)
def get_rules(x_user_id: str | None = Header(default=None), st: DemoState = Depends(get_state)):
    """What the system enforces (read by everyone); the administrator sees the edit controls."""
    return _rules_out(st, _actor(st, x_user_id))


@router.put("/ustawienia/reguly", response_model=s.RegulyOut)
def set_rules(body: s.RegulyIn, x_user_id: str | None = Header(default=None), st: DemoState = Depends(get_state)):
    """After an amendment: new values with the legal basis of the change. Every deadline is recomputed."""
    who = _actor(st, x_user_id)
    _require_admin(who, "Wymagania z rozporządzenia")
    new = regulations.validate(body.wartosci)
    current = {**regulations.defaults(), **st.rule_overrides}
    for key, value in new.items():
        if current[key] != value:
            st.rule_changes.append(RuleChangeRecord(key, current[key], value, body.podstawa_zmiany.strip(), who,
                                                    st.clock.today()))
    default = regulations.defaults()
    merged = {k: v for k, v in {**st.rule_overrides, **new}.items() if v != default[k]}
    st.apply_rules(merged)
    st.hr_reports.clear()
    return _rules_out(st, who)


@router.delete("/ustawienia/reguly", response_model=s.RegulyOut)
def reset_rules(x_user_id: str | None = Header(default=None), st: DemoState = Depends(get_state)):
    """Back to the published regulation (reguly.json); the change is logged."""
    who = _actor(st, x_user_id)
    _require_admin(who, "Wymagania z rozporządzenia")
    default = regulations.defaults()
    for key, value in st.rule_overrides.items():
        st.rule_changes.append(RuleChangeRecord(key, value, default[key], "przywrócenie wartości z rozporządzenia",
                                                who, st.clock.today()))
    st.apply_rules({})
    st.hr_reports.clear()
    return _rules_out(st, who)


# ---------------------------------------------------------------- visibility + AI switches (office)

def _office_out(st: DemoState, who: str) -> s.UstawieniaUrzeduOut:
    return s.UstawieniaUrzeduOut(
        zakres_widocznosci=st.settings.visibility_scope.value, asystent_ai=st.ai_office,
        hr_partner=st.hr_partner_office, tryb_ai_serwera=s.TrybAI(st.ai_mode.upper()), moze_edytowac=who == HR)


@router.get("/ustawienia/urzad", response_model=s.UstawieniaUrzeduOut)
def get_office(x_user_id: str | None = Header(default=None), st: DemoState = Depends(get_state)):
    return _office_out(st, _actor(st, x_user_id))


@router.put("/ustawienia/urzad", response_model=s.UstawieniaUrzeduOut)
def set_office(body: s.UstawieniaUrzeduIn, x_user_id: str | None = Header(default=None),
               st: DemoState = Depends(get_state)):
    who = _actor(st, x_user_id)
    _require_admin(who, "Ustawienia urzędu")
    if body.zakres_widocznosci is not None:
        st.settings = dataclasses.replace(st.settings, visibility_scope=VisibilityScope(body.zakres_widocznosci))
    if body.asystent_ai is not None:
        st.ai_office = body.asystent_ai
        st.hr_reports.clear()
    if body.hr_partner is not None:
        st.hr_partner_office = body.hr_partner
    return _office_out(st, who)


# ---------------------------------------------------------------- my own switch

def _mine(st: DemoState, who: str) -> s.MojAsystentOut:
    return s.MojAsystentOut(asystent_ai=who not in st.ai_off_for, hr_partner=who not in st.hr_partner_off_for,
                            asystent_ai_w_urzedzie=st.ai_office, hr_partner_w_urzedzie=st.hr_partner_office)


@router.get("/me/asystent", response_model=s.MojAsystentOut)
def get_my_assistant(x_user_id: str | None = Header(default=None), st: DemoState = Depends(get_state)):
    return _mine(st, _actor(st, x_user_id))


@router.put("/me/asystent", response_model=s.MojAsystentOut)
def set_my_assistant(body: s.MojAsystentIn, x_user_id: str | None = Header(default=None),
                     st: DemoState = Depends(get_state)):
    """Turn the AI assistant / HR partner off (or back on) for me only."""
    who = _actor(st, x_user_id)
    if body.asystent_ai is not None:
        (st.ai_off_for.discard if body.asystent_ai else st.ai_off_for.add)(who)
    if body.hr_partner is not None:
        (st.hr_partner_off_for.discard if body.hr_partner else st.hr_partner_off_for.add)(who)
    return _mine(st, who)
