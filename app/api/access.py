"""Identity and access checks shared by all routers – every endpoint asks the same policy
(app/domain/access.py, built in DemoState.policy() from the supervisor tree, office settings and deputies).

Identity on the demo: `X-User-Id` = employee id from pracownicy.json, or `kadry` (HR / administrator).
Without the header the caller is treated as HR (reads everything, acts as nobody's evaluator)."""
from __future__ import annotations

from app.domain.cycle import EvaluationCycle
from app.domain.errors import NotAuthorized

from .errors import ApiProblem
from .state import HR, DemoState


def actor(st: DemoState, x_user_id: str | None) -> str:
    if x_user_id is None or x_user_id == HR:
        return HR
    if st.directory.get(x_user_id) is None:
        raise ApiProblem(403, "NIEZNANY_UZYTKOWNIK", "Nieznany użytkownik (nagłówek X-User-Id).")
    return x_user_id


def require_read(st: DemoState, who: str, c: EvaluationCycle) -> None:
    if not st.policy().can_read(who, c.employee_id, c.evaluator_id):
        raise NotAuthorized("Nie masz dostępu do tej oceny.")


def require_evaluator(st: DemoState, who: str, c: EvaluationCycle, message: str) -> None:
    """Writing: only the direct evaluator or their active deputy."""
    if not st.policy().can_act_as_evaluator(who, c.employee_id, c.evaluator_id):
        raise NotAuthorized(message)


def require_working_material(st: DemoState, who: str, c: EvaluationCycle, message: str) -> None:
    """Notes, prep, drafts, evidence, HR hints: evaluator, deputy or HR – not the evaluated person,
    not managers higher up (they read the evaluation itself, not the evaluator's working notes)."""
    if not st.policy().can_see_working_material(who, c.employee_id, c.evaluator_id):
        raise NotAuthorized(message)
