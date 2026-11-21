"""Who may see and who may act on an evaluation – one policy instead of checks scattered over endpoints.

- The supervisor tree comes from "who evaluates whom" (`evaluator_of`). A manager can also be evaluated
  by someone higher up; then they have both roles, with different rights.
- READ (the evaluation sheet, status, deadlines): the evaluated person (own evaluation only), the evaluator,
  the evaluator's active deputy, and – depending on the office setting – everyone above in the tree
  (`SUBTREE`, default) or only the direct evaluator (`DIRECT`). Administrators (HR) read everything.
- WRITE / evaluator's working material (criteria, scores, notes, drafts, prep, evidence, HR hints): only the
  direct evaluator (art. 81 ust. 1 of the Act) or their active deputy. Managers higher up only read.
- An evaluator is never shown the working material about themselves (e.g. their own boss's notes).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping


class VisibilityScope(str, Enum):
    SUBTREE = "PODDRZEWO"  # a manager sees evaluations in their whole subtree (read only below direct reports)
    DIRECT = "BEZPOSREDNI"  # only the people they evaluate themselves


@dataclass(frozen=True)
class AccessPolicy:
    evaluator_of: Mapping[str, str | None]  # employee id -> their evaluator's id
    scope: VisibilityScope = VisibilityScope.SUBTREE
    deputies: Mapping[str, frozenset[str]] = field(default_factory=dict)  # evaluator -> deputies active today
    admins: frozenset[str] = frozenset()  # HR / office administrator: read everything

    # ---- tree -------------------------------------------------------------------------------------
    def direct_reports(self, manager: str) -> set[str]:
        return {e for e, boss in self.evaluator_of.items() if boss == manager}

    def subtree(self, manager: str) -> set[str]:
        """Everyone below `manager` (cycles in the data are ignored, never loop)."""
        seen: set[str] = set()
        todo = [manager]
        while todo:
            for e in self.direct_reports(todo.pop()):
                if e not in seen and e != manager:
                    seen.add(e)
                    todo.append(e)
        return seen

    def acts_for(self, user: str) -> set[str]:
        """The user and every evaluator they currently stand in for."""
        return {user} | {ev for ev, deps in self.deputies.items() if user in deps}

    # ---- questions ----------------------------------------------------------------------------------
    def is_admin(self, user: str) -> bool:
        return user in self.admins

    def visible_employees(self, user: str) -> set[str]:
        """People whose evaluations `user` may read as a manager (not counting their own)."""
        if self.is_admin(user):
            return set(self.evaluator_of)
        out: set[str] = set()
        for who in self.acts_for(user):
            out |= self.subtree(who) if self.scope is VisibilityScope.SUBTREE else self.direct_reports(who)
        out.discard(user)
        return out

    def can_read(self, user: str, employee: str, evaluator: str | None) -> bool:
        return (user == employee or self.is_admin(user) or self.can_act_as_evaluator(user, employee, evaluator)
                or employee in self.visible_employees(user))

    def can_act_as_evaluator(self, user: str, employee: str, evaluator: str | None) -> bool:
        """Write access and the evaluator's working material: the evaluator or their active deputy –
        never the evaluated person (a deputy standing in for their own boss cannot evaluate themselves)."""
        if evaluator is None or user == employee:
            return False
        return user == evaluator or user in self.deputies.get(evaluator, frozenset())

    def can_see_working_material(self, user: str, employee: str, evaluator: str | None) -> bool:
        """Notes, prep, drafts, evidence, HR hints: evaluator, deputy, HR – never the evaluated person."""
        return user != employee and (self.is_admin(user) or self.can_act_as_evaluator(user, employee, evaluator))
