"""Who decides an objection to an evaluation (art. 83 ust. 1 of the Act).

Normally the director general of the office. Edge cases (office setting, config/ustawienia_urzedu.json):
- the office has no director general (footnote 17 of the KPRM forms: "W urzędzie, w którym przepisy nie
  przewidują tworzenia stanowiska dyrektora generalnego urzędu, sprzeciw składa się do kierownika tego urzędu");
- the evaluated person is the head of the office (sheet A) – or would decide their own objection: the office
  chooses either the superior body (ORGAN_NADRZEDNY) or a re-examination by the evaluator (PONOWNE_ROZPATRZENIE);
- the office routes objections to the evaluator's own supervisor (PRZELOZONY_PRZELOZONEGO, an office decision –
  the Act names the director general). When the evaluator has no supervisor (top of the structure), or that
  supervisor is the evaluated person, the objection falls back to the ordinary route (DG / head of the office).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Route(str, Enum):
    DIRECTOR_GENERAL = "DYREKTOR_GENERALNY"  # art. 83 ust. 1 (default)
    SKIP_LEVEL = "PRZELOZONY_PRZELOZONEGO"  # the evaluator's supervisor (office setting)


class HeadMode(str, Enum):
    SUPERIOR_BODY = "ORGAN_NADRZEDNY"
    RE_EXAMINATION = "PONOWNE_ROZPATRZENIE"


@dataclass(frozen=True)
class ObjectionPolicy:
    director_general: str = "kadry"
    office_has_director_general: bool = True
    when_office_head: HeadMode = HeadMode.SUPERIOR_BODY
    superior_body: str = "kadry"
    route: Route = Route.DIRECTOR_GENERAL


@dataclass(frozen=True)
class Reviewer:
    id: str
    basis: str


def objection_reviewer(policy: ObjectionPolicy, employee_id: str, evaluator_id: str,
                       employee_is_office_head: bool, office_head_id: str | None,
                       evaluator_supervisor_id: str | None = None) -> Reviewer:
    def head_case(why: str) -> Reviewer:
        if policy.when_office_head is HeadMode.RE_EXAMINATION:
            return Reviewer(evaluator_id, f"{why} – sprzeciw podlega ponownemu rozpatrzeniu przez oceniającego "
                                          "(ustawienie urzędu)")
        return Reviewer(policy.superior_body, f"{why} – sprzeciw rozpatruje organ nadrzędny (ustawienie urzędu)")

    if employee_is_office_head or employee_id == office_head_id:
        return head_case("Oceniany jest kierownikiem urzędu")
    if policy.route is Route.SKIP_LEVEL:
        boss = evaluator_supervisor_id
        if boss and boss not in (employee_id, evaluator_id):
            return Reviewer(boss, "Sprzeciw rozpatruje przełożony oceniającego (ustawienie urzędu)")
        fallback = _ordinary(policy, employee_id, office_head_id, head_case)
        return Reviewer(fallback.id, f"Oceniający nie ma przełożonego – {fallback.basis[0].lower()}{fallback.basis[1:]}")
    return _ordinary(policy, employee_id, office_head_id, head_case)


def _ordinary(policy: ObjectionPolicy, employee_id: str, office_head_id: str | None, head_case) -> Reviewer:
    """Art. 83 ust. 1: the director general, or the head of the office where there is no DG."""
    if not policy.office_has_director_general:
        head = office_head_id or policy.director_general
        if head == employee_id:
            return head_case("Oceniany kieruje urzędem")
        return Reviewer(head, "W urzędzie nie ma dyrektora generalnego – sprzeciw rozpatruje kierownik urzędu "
                              "(przypis 17 do wzoru arkusza)")
    if policy.director_general == employee_id:
        return head_case("Oceniany jest dyrektorem generalnym")
    return Reviewer(policy.director_general, "Sprzeciw rozpatruje dyrektor generalny urzędu (art. 83 ust. 1 ustawy)")
