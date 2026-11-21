"""Identity and access checks shared by all routers – every endpoint asks the same policy
(app/domain/access.py, built in DemoState.policy() from the supervisor tree, office settings and deputies).

Identity comes from `auth.current_user` (app/api/auth.py) – the only source of "who":
AUTH_MODE=demo: `X-User-Id` = employee id from pracownicy.json, or `kadry` (HR / administrator); without the
header the caller is treated as HR. AUTH_MODE=session: the signed session cookie; `X-User-Id` is ignored."""
from __future__ import annotations

from app.domain.cycle import EvaluationCycle
from app.domain.errors import NotAuthorized

from .auth import current_user
from .state import DemoState

# Routers call `actor(st, x_user_id)`; it is `current_user` – never resolve identity anywhere else.
actor = current_user


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
