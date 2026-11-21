"""AI suggestions for the evaluator (UC1, UC4, UC5, UC7). Every feature:

- works without AI (templates / rules from the catalog, `source` = "SZABLON" or "REGULY"),
- pseudonymises everything it sends to the model and restores names in the answer,
- validates every model answer before it reaches the user (labels from the closed list only, quotes must
  exist in the note, ids must exist, no leftover tokens) and falls back when the answer is rejected,
- never applies anything: it returns proposals, the evaluator decides.

The model is a port (AiModel). AiUnavailable / AiInvalidOutput -> fallback; NotImplementedError is NOT
caught, so AI_MODE=api fails loudly until that adapter exists.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from string import Template
from typing import Any, Callable, Iterable, Iterator, Literal, Mapping, Sequence

from app.domain.calendar import WorkingCalendar
from app.domain.cycle import EvaluationCycle, PreviousEvaluation
from app.domain.deadlines import Absence
from app.domain.employee import Employee
from app.domain.meeting_prep import build_meeting_prep
from app.domain.notes import CriterionEvidence, Note, Sentiment, evidence_by_criterion
from app.domain.rulebook import RuleBook
from app.domain.scoring import EvaluationResult, Outcome, compute_result

from .ports import AiInvalidOutput, AiModel, AiTask, AiUnavailable
from .privacy import Pseudonymizer

Source = Literal["AI", "SZABLON", "REGULY"]
DraftKind = Literal["UZASADNIENIE", "IPRZ", "UMOTYWOWANIE_STOPNIA"]
PrepKind = Literal["OCENIAJACA", "ROZPOCZYNAJACA"]
SignalKind = Literal["PRZECIAZENIE", "DLUGA_NIEOBECNOSC", "ZMIANA_OBOWIAZKOW", "SPADEK_OCEN", "DO_DOCENIENIA"]

_PROMPTS = Path(__file__).resolve().parent / "prompts"
_LEFTOVER_TOKEN = re.compile(r"\[(OSOBA_K?\d+|PESEL|EMAIL|TELEFON)\]")  # OSOBA_K = backend.llm guard
_BANNED_IN_HR = ("depresj", "chorob", "diagnoz", "zaburzeni", "psychiatr", "terapi", "leczeni")

# what the regulation requires the conversation to cover, and how the questions should look
_PREP_LAW = {
    "ROZPOCZYNAJACA": "Przepisy (§ 5 ust. 1 rozporządzenia) wymagają omówienia: głównych obowiązków wynikających "
                      "z opisu stanowiska, kryteriów obowiązkowych i dodatkowych, oczekiwań oceniającego co do sposobu "
                      "spełniania kryteriów oraz – jeśli to uzasadnione – celów na okres oceny i sposobu ich realizacji.",
    "OCENIAJACA": "Przepisy (§ 10 rozporządzenia) wymagają omówienia: głównych obowiązków i sposobu ich realizacji "
                  "w odniesieniu do kryteriów, realizacji celów oraz kierunków rozwoju i potrzeb szkoleniowych.",
}
_PREP_QUESTION_STYLE = {
    "ROZPOCZYNAJACA": "pytań otwartych o oczekiwania i cele na nadchodzący okres oceny (okres dopiero się zaczyna "
                      "– nie pytaj o przeszłe sytuacje)",
    "OCENIAJACA": "pytań otwartych o konkretne sytuacje z okresu oceny",
}


def _start_questions(name: str, indicators: Sequence[str]) -> tuple[str, ...]:
    """Forward-looking questions for the starting conversation (§ 5 ust. 1 pkt 3: expectations per criterion)."""
    out = []
    if indicators:
        ind = indicators[0].strip().rstrip(".")
        out.append(f"Jak w Twoich obowiązkach będzie widać: „{ind[:1].lower() + ind[1:]}”?")
    out.append(f"Czego potrzebujesz, żeby kryterium „{name}” spełniać co najmniej na poziomie oczekiwań?")
    return tuple(out)


def _prompt(name: str, **values: Any) -> str:
    return Template((_PROMPTS / f"{name}.md").read_text(encoding="utf-8")).substitute(**values)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip(" \t\n.,;:!?\"'„”«»()–-")


def _trigrams(text: str) -> set[str]:
    words = re.findall(r"\w+", text.casefold())
    return {w[i:i + 3] for w in words if len(w) > 2 for i in range(len(w) - 2)}


def _similarity(a: str, b: str) -> float:
    ta, tb = _trigrams(a), _trigrams(b)
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


_NAME_ROWS = re.compile(r"^\|\s*(imię|nazwisko|imię i nazwisko|miejscowość)\b.*$|^.*podpisano elektronicznie.*$",
                        re.IGNORECASE | re.MULTILINE)


def _style_example(text: str, limit: int = 2500) -> str:
    """A KPRM sample sheet as a style example: rows with names and signatures removed, trimmed."""
    return re.sub(r"\n{3,}", "\n\n", _NAME_ROWS.sub("", text)).strip()[:limit]


def _str_list(value: Any, max_items: int, max_len: int = 400) -> list[str]:
    if not isinstance(value, list):
        raise AiInvalidOutput("Oczekiwano listy.")
    out = [v.strip() for v in value if isinstance(v, str) and v.strip()]
    if any(len(v) > max_len for v in out):
        raise AiInvalidOutput("Zbyt długi element listy.")
    return out[:max_items]


# ---------------------------------------------------------------- catalog (asystent.json + KPRM examples)

@dataclass(frozen=True)
class AiCatalog:
    questions: dict[str, list[str]]
    development: dict[str, list[str]]
    hr: dict[str, Any]
    keywords: dict[str, list[str]]
    templates: dict[str, str]
    classify_examples: list[dict]
    sample_evaluations: dict[str, str] = field(default_factory=dict)  # file name -> filled KPRM sheet text

    @classmethod
    def from_raw(cls, raw: dict, sample_evaluations: Iterable[tuple[str, str]] = ()) -> AiCatalog:
        return cls(
            questions=raw["pytania"],
            development=raw["dzialania_rozwojowe"],
            hr=raw["hr_partner"],
            keywords=raw["slowa_kluczowe_kryteriow"],
            templates=raw["szablony"],
            classify_examples=raw.get("przyklady_klasyfikacji", []),
            sample_evaluations=dict(sample_evaluations),
        )


# ---------------------------------------------------------------- results (mapped to app/api/schemas.py by the API layer)

@dataclass(frozen=True)
class ClassificationSuggestion:
    criterion_id: str
    criterion_name: str
    indicator: str | None
    sentiment: Sentiment | None
    confidence: float
    quote: str


@dataclass(frozen=True)
class NoteClassification:
    note_id: str
    suggestions: tuple[ClassificationSuggestion, ...]
    status: Literal["SUGESTIA", "DO_PRZYPISANIA"]  # DO_PRZYPISANIA = low confidence or fallback: ask the evaluator
    source: Source


@dataclass(frozen=True)
class Draft:
    kind: DraftKind
    text: str
    source: Source
    note_ids: tuple[str, ...]
    key: str  # changes when inputs change -> the UI marks an older draft as stale


@dataclass(frozen=True)
class CriterionSuggestion:
    criterion_id: str
    name: str
    reason: str


@dataclass(frozen=True)
class CriteriaSuggestions:
    items: tuple[CriterionSuggestion, ...]
    source: Source


@dataclass(frozen=True)
class HrSignal:
    kind: SignalKind
    description: str
    evidence: tuple[str, ...]
    recommendations: tuple[str, ...]


@dataclass(frozen=True)
class HrReport:
    signals: tuple[HrSignal, ...]
    source: Source


@dataclass(frozen=True)
class PrepCriterion:
    criterion_id: str
    name: str
    mandatory: bool
    positive: int
    negative: int
    examples: tuple[Note, ...]
    gaps: tuple[str, ...]  # behavioural indicators without any observation -> ask about them
    questions: tuple[str, ...]


@dataclass(frozen=True)
class ConversationPrep:
    kind: PrepKind
    cycle_id: str
    employee_name: str
    position: str
    sheet: str
    goal: str
    evaluation_deadline: date
    days_to_deadline: int
    previous_evaluation: PreviousEvaluation | None
    goals: tuple[str, ...]
    criteria: tuple[PrepCriterion, ...]
    strengths: tuple[str, ...]
    difficult_topics: tuple[str, ...]
    hr_signals: tuple[HrSignal, ...]
    development: tuple[str, ...]
    plan_minutes: tuple[tuple[str, int], ...]
    source: Source  # of the texts; the skeleton always comes from data


@dataclass(frozen=True)
class AiCall:
    """What left the application (for the AiInteraction log)."""

    function: str
    model: str
    prompt: str  # pseudonymised
    response: str
    ok: bool
    error: str = ""


# ---------------------------------------------------------------- service

class AiSuggestionService:
    def __init__(
        self,
        rules: RuleBook,
        model: AiModel,
        catalog: AiCatalog,
        calendar: WorkingCalendar | None = None,
        min_confidence: float = 0.6,
        on_call: Callable[[AiCall], None] | None = None,
    ):
        self.rules = rules
        self.model = model
        self.catalog = catalog
        self.calendar = calendar or WorkingCalendar()
        self.min_confidence = min_confidence
        self.calls: list[AiCall] = []
        self._on_call = on_call
        self._drafts: dict[str, Draft] = {}
        self._system = (_PROMPTS / "system.md").read_text(encoding="utf-8")
        self._level_rank = {b.level.casefold(): i for i, b in enumerate(rules.level_bands)}

    # ---- plumbing ------------------------------------------------------------------------------
    def _record(self, call: AiCall) -> None:
        self.calls.append(call)
        if self._on_call:
            self._on_call(call)

    def _ask_json(self, function: str, prompt: str, schema: dict, task: AiTask,
                  validate: Callable[[dict], Any]) -> Any | None:
        """Model answer, validated; None = use the fallback. NotImplementedError propagates on purpose."""
        if not self.model.available():
            return None
        try:
            raw = self.model.complete_json(self._system, prompt, schema, task)
            try:
                result = validate(raw)
            except (TypeError, AttributeError, KeyError) as e:  # answer of an unexpected shape
                raise AiInvalidOutput(f"Nieoczekiwany kształt odpowiedzi: {e}") from e
        except (AiUnavailable, AiInvalidOutput) as e:
            self._record(AiCall(function, self.model.name, prompt, "", False, f"{type(e).__name__}: {e}"))
            return None
        self._record(AiCall(function, self.model.name, prompt, json.dumps(raw, ensure_ascii=False), True))
        return result

    def _people(self, *employees: Employee | None) -> Pseudonymizer:
        return Pseudonymizer((e.first_name, e.last_name) for e in employees if e is not None)

    def _criteria_ids(self, cycle: EvaluationCycle) -> list[str]:
        return list(cycle.criteria_ids(self.rules))

    def _current_result(self, cycle: EvaluationCycle) -> EvaluationResult | None:
        if cycle.result is not None:
            return cycle.result
        ids = self._criteria_ids(cycle)
        if ids and all(cycle.scores.get(c) is not None for c in ids):
            return compute_result([cycle.scores[c] for c in ids], self.rules)
        return None

    def _weak_strong(self, cycle: EvaluationCycle, ev: dict[str, CriterionEvidence]) -> tuple[list[str], list[str]]:
        weak, strong = [], []
        for cid in self._criteria_ids(cycle):
            pts = cycle.scores.get(cid)
            if pts is not None:
                (weak if pts <= 3 else strong if pts >= 7 else []).append(cid)
            elif ev[cid].balance < 0:
                weak.append(cid)
            elif ev[cid].balance > 0:
                strong.append(cid)
        return weak, strong

    def _names(self, ids: Iterable[str]) -> str:
        return ", ".join(self.rules.criterion_name(c).lower() for c in ids) or "brak"

    # ---- 1. note classification (UC4/UC5 evidence) ---------------------------------------------
    def classify_note(self, note: Note, sheet: str, additional: Sequence[str] = (),
                      people: Sequence[Employee] = ()) -> NoteClassification:
        allowed = list(dict.fromkeys([*self.rules.mandatory(sheet), *additional]))
        pseudo = self._people(*people)
        masked = pseudo.mask(note.text)
        labels = "\n".join(
            f"{cid} | {self.rules.criteria[cid].name} | "
            + "; ".join(f"{i}. {w}" for i, w in enumerate(self.rules.criteria[cid].indicators, 1))
            for cid in allowed)
        examples = "\n".join(
            f'Notatka: "{ex["notatka"]}"\nOdpowiedź: {json.dumps({"etykiety": ex["etykiety"]}, ensure_ascii=False)}'
            for ex in self.catalog.classify_examples)
        schema = {
            "type": "object",
            "properties": {"etykiety": {"type": "array", "maxItems": 3, "items": {
                "type": "object",
                "properties": {
                    "kryterium": {"type": "string", "enum": allowed},
                    "wskaznik": {"type": "integer"},
                    "wydzwiek": {"type": "string", "enum": [s.value for s in Sentiment]},
                    "pewnosc": {"type": "number"},
                    "cytat": {"type": "string"},
                },
                "required": ["kryterium", "wskaznik", "wydzwiek", "pewnosc", "cytat"]}}},
            "required": ["etykiety"],
        }

        def validate(raw: dict) -> list[ClassificationSuggestion]:
            items = raw.get("etykiety")
            if not isinstance(items, list):
                raise AiInvalidOutput("Brak listy „etykiety”.")
            out: dict[str, ClassificationSuggestion] = {}
            for it in items:
                if not isinstance(it, dict):
                    continue
                cid, quote = it.get("kryterium"), str(it.get("cytat", ""))
                if cid not in allowed or not quote.strip() or _norm(quote) not in _norm(masked):
                    continue  # label outside the list or a quote the note does not contain
                try:
                    sentiment = Sentiment(it.get("wydzwiek"))
                    conf = float(it.get("pewnosc"))
                    idx = int(it.get("wskaznik", 0))
                except (TypeError, ValueError):
                    continue
                if not 0 <= conf <= 1:
                    continue
                indicators = self.rules.criteria[cid].indicators
                indicator = indicators[idx - 1] if 1 <= idx <= len(indicators) else None
                s = ClassificationSuggestion(cid, self.rules.criteria[cid].name, indicator, sentiment,
                                             round(conf, 2), pseudo.unmask(quote.strip()))
                if cid not in out or out[cid].confidence < s.confidence:
                    out[cid] = s
            if items and not out:
                raise AiInvalidOutput("Żadna etykieta nie przeszła walidacji.")
            return sorted(out.values(), key=lambda s: -s.confidence)[:3]

        prompt = _prompt("classify", labels=labels, examples=examples, note=masked)
        suggestions = self._ask_json("klasyfikacja_notatki", prompt, schema, "classify", validate)
        if suggestions is not None:
            confident = bool(suggestions) and suggestions[0].confidence >= self.min_confidence
            return NoteClassification(note.id, tuple(suggestions), "SUGESTIA" if confident else "DO_PRZYPISANIA", "AI")

        # fallback: text similarity to criterion names and behavioural indicators, no sentiment
        scored = []
        for cid in allowed:
            c = self.rules.criteria[cid]
            best = max(((_similarity(note.text, w), w) for w in c.indicators), default=(0.0, None))
            score = max(best[0], _similarity(note.text, c.name))
            scored.append((score, cid, best[1]))
        scored.sort(reverse=True)
        top = [ClassificationSuggestion(cid, self.rules.criteria[cid].name, ind, None, round(min(score * 2, 1.0), 2), "")
               for score, cid, ind in scored[:3] if score > 0]
        return NoteClassification(note.id, tuple(top), "DO_PRZYPISANIA", "REGULY")

    # ---- 2. drafts: justification, IPRZ conclusions, grade motivation (UC5) ---------------------
    def _draft_context(self, kind: DraftKind, cycle: EvaluationCycle, employee: Employee,
                       notes: Sequence[Note]) -> dict[str, Any]:
        ids = self._criteria_ids(cycle)
        ev = evidence_by_criterion(notes, ids)
        weak, strong = self._weak_strong(cycle, ev)
        return {"ids": ids, "ev": ev, "weak": weak, "strong": strong, "result": self._current_result(cycle)}

    def _draft_key(self, kind: DraftKind, cycle: EvaluationCycle, notes: Sequence[Note]) -> str:
        payload = json.dumps([kind, cycle.id, sorted(cycle.scores.items()),
                              sorted((n.id, n.text, n.criterion_id, n.sentiment and n.sentiment.value) for n in notes)],
                             ensure_ascii=False, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def _draft_template(self, kind: DraftKind, cycle: EvaluationCycle, employee: Employee,
                        ctx: dict[str, Any]) -> tuple[str, tuple[str, ...]]:
        ev, weak, strong, result = ctx["ev"], ctx["weak"], ctx["strong"], ctx["result"]
        used: list[str] = []

        def proofs(cids: list[str], positive: bool) -> str:
            lines = []
            for cid in cids:
                bucket = ev[cid].positive if positive else ev[cid].negative
                for n in bucket[:2]:
                    used.append(n.id)
                    lines.append(f"– {self.rules.criterion_name(cid)}: {n.text} ({n.on:%d.%m.%Y})")
            return "\n".join(lines) or "– brak notatek z okresu oceny przypisanych do tych kryteriów"

        values = {
            "imie": employee.full_name,
            "okres_od": f"{(cycle.period_from or cycle.criteria_set_on or cycle.start_date):%d.%m.%Y}",
            "okres_do": f"{(cycle.period_to or cycle.meeting_date or date.today()):%d.%m.%Y}",
            "poziom": result.level if result else "nie wyliczono (brak wszystkich ocen cząstkowych)",
            "slabe_kryteria": self._names(weak),
            "mocne_strony": self._names(strong),
            "dowody_negatywne": proofs(weak, False),
            "dowody_pozytywne": proofs(strong, True),
        }
        t = self.catalog.templates
        if kind == "IPRZ":
            actions = [a for cid in (weak or ctx["ids"]) for a in self.catalog.development.get(cid, [])[:2]]
            text = t["iprz"].format(dzialania="\n".join(f"– {a}" for a in dict.fromkeys(actions)) or "– do uzgodnienia na rozmowie")
        elif kind == "UMOTYWOWANIE_STOPNIA":
            text = t["umotywowanie_stopnia"].format(**values)
        else:
            negative = result is not None and result.outcome is Outcome.NEGATIVE
            text = t["uzasadnienie_negatywna" if negative else "uzasadnienie_pozytywna"].format(**values)
        return text, tuple(dict.fromkeys(used))

    def _draft_prompt(self, kind: DraftKind, cycle: EvaluationCycle, employee: Employee, notes: Sequence[Note],
                      ctx: dict[str, Any], pseudo: Pseudonymizer) -> str:
        result = ctx["result"]
        what = {"UZASADNIENIE": "uzasadnienia przyznanej oceny okresowej",
                "IPRZ": "wniosków dotyczących indywidualnego programu rozwoju zawodowego (IPRZ)",
                "UMOTYWOWANIE_STOPNIA": "umotywowania wniosku o przyznanie kolejnego stopnia służbowego"}[kind]
        actions = "; ".join(a for cid in (ctx["weak"] or ctx["ids"]) for a in self.catalog.development.get(cid, [])[:2])
        instructions = {
            "UZASADNIENIE": "Odnieś się do kryteriów z najniższymi i najwyższymi ocenami i podaj konkretne zachowania "
                            "z notatek. 120–250 słów. Przy ocenie negatywnej wskaż wprost, które kryteria nie spełniają "
                            "oczekiwań i dlaczego (§ 11 ust. 3).",
            "IPRZ": f"Zaproponuj 3–5 konkretnych działań rozwojowych powiązanych z kryteriami do poprawy, jako listę "
                    f"zaczynającą się od myślników. Możesz korzystać z katalogu urzędu: {actions or 'brak'}.",
            "UMOTYWOWANIE_STOPNIA": "80–150 słów, oparte na mocnych stronach i osiągnięciach z notatek (art. 89 ust. 1 ustawy).",
        }[kind]
        negative = result is not None and result.outcome is Outcome.NEGATIVE
        # never show the model a sample about the same (fictional) person – it would copy facts from it
        own = re.compile(rf"\b({re.escape(employee.first_name)}|{re.escape(employee.last_name)})\b", re.IGNORECASE)
        samples = [(name, t) for name, t in sorted(self.catalog.sample_evaluations.items()) if not own.search(t)]
        pick = [t for name, t in samples if ("neg" in name) == negative] or [t for _, t in samples] or [""]
        notes_txt = "\n".join(
            f"{n.id} | {n.on:%Y-%m-%d} | {self.rules.criterion_name(n.criterion_id) if n.criterion_id else '-'} | "
            f"{n.sentiment.value if n.sentiment else '-'} | {pseudo.mask(n.text)}"
            for n in sorted(notes, key=lambda n: n.on)) or "brak notatek"
        scores = "\n".join(f"- {self.rules.criterion_name(c)}: {cycle.scores.get(c, 'brak')}" for c in ctx["ids"])
        return _prompt(
            "draft", what=what, person=pseudo.token_for(employee.first_name, employee.last_name),
            position=employee.position, sheet=cycle.sheet,
            period=f"{cycle.period_from or cycle.start_date} – {cycle.period_to or 'w toku'}",
            result=f"{result.outcome.value}, {result.level}, średnia {result.average_display}" if result else "jeszcze nie wyliczony",
            scores=scores, notes=notes_txt, instructions=instructions, example=_style_example(pick[0]))

    def draft(self, kind: DraftKind, cycle: EvaluationCycle, employee: Employee, notes: Sequence[Note]) -> Draft:
        key = self._draft_key(kind, cycle, notes)
        if key in self._drafts:
            return self._drafts[key]
        ctx = self._draft_context(kind, cycle, employee, notes)
        pseudo = self._people(employee)
        note_ids = {n.id for n in notes}
        prompt = self._draft_prompt(kind, cycle, employee, notes, ctx, pseudo) + (
            '\n\nZwróć JSON z polami: "tekst" (gotowy szkic do wklejenia w arkusz, bez nagłówka) '
            'i "notatki" (lista identyfikatorów notatek, na których oparłeś szkic).')
        schema = {"type": "object", "properties": {"tekst": {"type": "string"},
                                                   "notatki": {"type": "array", "items": {"type": "string"}}},
                  "required": ["tekst", "notatki"]}

        def validate(raw: dict) -> tuple[str, tuple[str, ...]]:
            text = pseudo.unmask(str(raw.get("tekst", ""))).strip()
            if not 30 <= len(text) <= 5000:
                raise AiInvalidOutput("Szkic jest pusty albo za długi.")
            if _LEFTOVER_TOKEN.search(text):
                raise AiInvalidOutput("Szkic zawiera nieznany znacznik danych osobowych.")
            used = raw.get("notatki") or []
            return text, tuple(str(i) for i in used if str(i) in note_ids)

        out = self._ask_json(f"szkic_{kind.lower()}", prompt, schema, "text", validate)
        if out is not None:
            text, used = out
            draft = Draft(kind, text, "AI", used, key)
        else:
            text, used = self._draft_template(kind, cycle, employee, ctx)
            draft = Draft(kind, text, "SZABLON", used, key)
        self._drafts[key] = draft
        return draft

    def draft_stream(self, kind: DraftKind, cycle: EvaluationCycle, employee: Employee,
                     notes: Sequence[Note]) -> Iterator[str]:
        """Text chunks for SSE. Names are restored on the fly; on failure before any text -> the template."""
        ctx = self._draft_context(kind, cycle, employee, notes)
        pseudo = self._people(employee)
        if self.model.available():
            prompt = self._draft_prompt(kind, cycle, employee, notes, ctx, pseudo) + \
                "\n\nZwróć wyłącznie tekst szkicu, bez JSON, nagłówków i komentarzy."
            buf, sent_any, parts = "", False, []
            try:
                for chunk in self.model.stream_text(self._system, prompt, "text"):
                    buf += chunk
                    parts.append(chunk)
                    cut = buf.rfind("[")
                    ready, buf = (buf, "") if cut == -1 or "]" in buf[cut:] else (buf[:cut], buf[cut:])
                    if ready:
                        sent_any = True
                        yield pseudo.unmask(ready)
                if buf:
                    yield pseudo.unmask(buf)
                self._record(AiCall(f"szkic_{kind.lower()}_stream", self.model.name, prompt, "".join(parts), True))
                return
            except AiUnavailable as e:
                self._record(AiCall(f"szkic_{kind.lower()}_stream", self.model.name, prompt, "", False, str(e)))
                if sent_any:
                    return
        yield self._draft_template(kind, cycle, employee, ctx)[0]

    # ---- 3. conversation prep note (UC4) --------------------------------------------------------
    def conversation_prep(self, cycle: EvaluationCycle, employee: Employee, evaluator: Employee | None,
                          notes: Sequence[Note], today: date, kind: PrepKind = "OCENIAJACA",
                          absences: Sequence[Absence] = ()) -> ConversationPrep:
        base = build_meeting_prep(cycle, employee, evaluator, self.rules, self.calendar, today)
        ids = [c.id for c in base.criteria]
        ev = evidence_by_criterion(notes, ids)
        weak, strong = self._weak_strong(cycle, ev)
        hr = self.hr_partner(cycle, employee, notes, absences, today, use_ai=False).signals

        criteria = []
        for c in base.criteria:
            e = ev[c.id]
            seen = {n.indicator for n in (*e.positive, *e.neutral, *e.negative) if n.indicator}
            gaps = c.indicators if e.total == 0 else tuple(w for w in c.indicators if seen and w not in seen)
            n_q = 3 if c.id in weak else 2
            # the catalog questions look back at the period; a starting conversation (§ 5) looks ahead
            questions = _start_questions(c.name, c.indicators) if kind == "ROZPOCZYNAJACA" \
                else tuple(self.catalog.questions.get(c.id, [])[:n_q])
            criteria.append(PrepCriterion(
                c.id, c.name, c.mandatory, len(e.positive), len(e.negative),
                tuple([*e.negative[:2], *e.positive[:1]]) if c.id in weak else tuple([*e.positive[:2], *e.negative[:1]]),
                gaps, questions))

        t = self.catalog.templates
        if kind == "ROZPOCZYNAJACA":
            # the period is 24 months, or 6 after a negative evaluation – name the actual deadline
            goal = t["cel_rozmowy_rozpoczynajaca"].format(
                termin_oceny=base.evaluation_deadline.strftime("%d.%m.%Y"))
            plan = (("Obowiązki z opisu stanowiska", 10), ("Kryteria i oczekiwania", 15),
                    ("Cele na okres oceny", 10), ("Pytania pracownika", 5))
        else:
            goal = t["cel_rozmowy_negatywna" if weak else "cel_rozmowy_pozytywna"].format(
                slabe_kryteria=self._names(weak), mocne_strony=self._names(strong))
            plan = (("Otwarcie i mocne strony", 5), ("Kryteria po kolei", 20),
                    ("Rozwój i wsparcie", 10), ("Ustalenia i kolejne kroki", 5))
        strengths = [f"{self.rules.criterion_name(c)}: {len(ev[c].positive)} pozytywnych obserwacji" for c in strong]
        difficult = [f"{self.rules.criterion_name(c)}: {len(ev[c].negative)} obserwacji poniżej oczekiwań – "
                     f"omów na konkretnych przykładach" for c in weak]
        development = list(dict.fromkeys(a for c in weak for a in self.catalog.development.get(c, [])[:1]))
        source: Source = "SZABLON"

        pseudo = self._people(employee, evaluator)
        evidence_txt = "\n".join(
            f"- {c.criterion_id} ({c.name}): {c.positive} / {c.negative}; "
            + "; ".join(f"„{pseudo.mask(n.text)}”" for n in c.examples) for c in criteria)
        prompt = _prompt(
            "prep", kind="rozmowa oceniająca" if kind == "OCENIAJACA" else "rozmowa rozpoczynająca ocenę",
            person=pseudo.token_for(employee.first_name, employee.last_name), position=employee.position,
            sheet=cycle.sheet, deadline=base.evaluation_deadline,
            previous=f"{base.previous_evaluation.outcome}, {base.previous_evaluation.level}" if base.previous_evaluation else "brak",
            goals="; ".join(base.goals) or "nie zapisano", evidence=evidence_txt,
            signals="\n".join(f"- {s.kind}: {pseudo.mask('; '.join(s.evidence))}" for s in hr) or "brak",
            criteria_ids=", ".join(ids), law=_PREP_LAW[kind], question_style=_PREP_QUESTION_STYLE[kind])
        list_of_str = {"type": "array", "items": {"type": "string"}}
        schema = {"type": "object", "properties": {
            "cel_rozmowy": {"type": "string"}, "mocne_strony": list_of_str, "trudne_tematy": list_of_str,
            "pytania": {"type": "object", "additionalProperties": list_of_str}, "propozycje_rozwoju": list_of_str},
            "required": ["cel_rozmowy", "mocne_strony", "trudne_tematy", "pytania", "propozycje_rozwoju"]}

        def validate(raw: dict) -> dict:
            goal_ai = pseudo.unmask(str(raw.get("cel_rozmowy", ""))).strip()
            if not 10 <= len(goal_ai) <= 500:
                raise AiInvalidOutput("Brak celu rozmowy.")
            questions = raw.get("pytania") or {}
            if not isinstance(questions, dict) or any(k not in ids for k in questions):
                raise AiInvalidOutput("Pytania dla kryteriów spoza listy.")
            out = {
                "goal": goal_ai,
                "strengths": [pseudo.unmask(s) for s in _str_list(raw.get("mocne_strony", []), 4)],
                "difficult": [pseudo.unmask(s) for s in _str_list(raw.get("trudne_tematy", []), 4)],
                "development": [pseudo.unmask(s) for s in _str_list(raw.get("propozycje_rozwoju", []), 4)],
                "questions": {k: [pseudo.unmask(q) for q in _str_list(v, 3, 300)] for k, v in questions.items()},
            }
            if any(_LEFTOVER_TOKEN.search(s) for s in [out["goal"], *out["strengths"], *out["difficult"], *out["development"]]):
                raise AiInvalidOutput("Nieznany znacznik danych osobowych.")
            return out

        ai = self._ask_json("przygotowanie_rozmowy", prompt, schema, "text", validate)
        if ai is not None:
            goal, source = ai["goal"], "AI"
            strengths, difficult = ai["strengths"] or strengths, ai["difficult"] or difficult
            development = ai["development"] or development
            criteria = [PrepCriterion(c.criterion_id, c.name, c.mandatory, c.positive, c.negative, c.examples, c.gaps,
                                      tuple(ai["questions"].get(c.criterion_id) or c.questions)) for c in criteria]

        return ConversationPrep(
            kind, cycle.id, base.employee_name, base.position, cycle.sheet, goal, base.evaluation_deadline,
            base.days_to_deadline, base.previous_evaluation, base.goals, tuple(criteria), tuple(strengths),
            tuple(difficult), tuple(hr), tuple(development), plan, source)

    # ---- 4. additional criteria (UC1) -----------------------------------------------------------
    def suggest_criteria(self, employee: Employee, sheet: str | None = None, description: str = "") -> CriteriaSuggestions:
        sheet = sheet or employee.sheet
        mandatory = self.rules.mandatory(sheet)
        candidates = [cid for cid in self.rules.criteria if cid not in mandatory]
        limit = self.rules.max_additional_criteria
        cand_txt = "\n".join(f"{cid} | {self.rules.criteria[cid].name} | {'; '.join(self.rules.criteria[cid].indicators)}"
                             for cid in candidates)
        prompt = _prompt("criteria", position=employee.position, unit=employee.unit or "-",
                         description=description.strip() or "nie podano", mandatory=self._names(mandatory),
                         candidates=cand_txt)
        schema = {"type": "object", "properties": {"propozycje": {"type": "array", "maxItems": limit, "items": {
            "type": "object", "properties": {"kryterium": {"type": "string", "enum": candidates},
                                             "uzasadnienie": {"type": "string"}},
            "required": ["kryterium", "uzasadnienie"]}}}, "required": ["propozycje"]}

        def validate(raw: dict) -> list[CriterionSuggestion]:
            items = raw.get("propozycje")
            if not isinstance(items, list):
                raise AiInvalidOutput("Brak listy „propozycje”.")
            out: dict[str, CriterionSuggestion] = {}
            for it in items:
                cid, reason = (it or {}).get("kryterium"), str((it or {}).get("uzasadnienie", "")).strip()
                if cid in candidates and cid not in out and 5 <= len(reason) <= 500:
                    out[cid] = CriterionSuggestion(cid, self.rules.criteria[cid].name, reason)
            if items and not out:
                raise AiInvalidOutput("Żadna propozycja nie przeszła walidacji.")
            return list(out.values())[:limit]

        ai = self._ask_json("podpowiedz_kryteriow", prompt, schema, "text", validate)
        if ai is not None:
            return CriteriaSuggestions(tuple(ai), "AI")

        text = f"{employee.position} {employee.unit} {description}".casefold()
        scored = []
        for cid in candidates:
            hits = [k for k in self.catalog.keywords.get(cid, []) if k.casefold() in text]
            if hits:
                scored.append((len(hits), cid, hits))
        scored.sort(key=lambda s: (-s[0], self.rules.criteria[s[1]].number))
        items = tuple(CriterionSuggestion(cid, self.rules.criteria[cid].name,
                                          f"Stanowisko i obowiązki wskazują na: {', '.join(hits)}.")
                      for _, cid, hits in scored[:limit])
        return CriteriaSuggestions(items, "REGULY")

    # ---- training needs (reports) -----------------------------------------------------------------
    def training_recommendation(self, ranking: Sequence[Any], scope: str, fallback: str) -> tuple[str, Source]:
        """Priorities for training from aggregated low scores (no names reach the model). `ranking` items have
        .criterion, .area, .low_scores, .evaluated; `fallback` = the template text (used when AI is off/fails)."""
        if not ranking:
            return fallback, "SZABLON"
        lines = "\n".join(f"- {r.criterion} | {r.area} | {r.low_scores}/{r.evaluated}" for r in ranking[:8])
        prompt = _prompt("training", scope=scope, ranking=lines)
        schema = {"type": "object", "properties": {"rekomendacja": {"type": "string"}}, "required": ["rekomendacja"]}

        def validate(raw: dict) -> str:
            text = str(raw.get("rekomendacja") or "").strip()
            if not 20 <= len(text) <= 1500 or _LEFTOVER_TOKEN.search(text):
                raise AiInvalidOutput("Rekomendacja pusta, za długa albo z pozostawionymi tokenami.")
            if any(b in text.casefold() for b in _BANNED_IN_HR):
                raise AiInvalidOutput("Rekomendacja wykracza poza rolę asystenta kadr.")
            return text

        text = self._ask_json("training_recommendation", prompt, schema, "text", validate)
        return (text, "AI") if text else (fallback, "SZABLON")

    # ---- 5. virtual HR partner (UC7) ------------------------------------------------------------
    def _detect_signals(self, cycle: EvaluationCycle, employee: Employee, notes: Sequence[Note],
                        absences: Sequence[Absence], today: date,
                        extra: Mapping[str, Sequence[str]] | None = None) -> list[HrSignal]:
        """`extra`: evidence from other sources per signal kind – the wellbeing checklist, working-time (RCP)
        indicators. Already aggregated; it raises the signal on its own."""
        extra = extra or {}
        cfg = self.catalog.hr
        kinds = cfg["sygnaly"]
        window = today - timedelta(days=30 * cfg["okno_notatek_miesiecy"])
        recent = [n for n in notes if n.on >= window]
        found: list[HrSignal] = []

        def keyword_notes(kind: str) -> list[Note]:
            keys = [k.casefold() for k in kinds[kind].get("slowa_kluczowe", [])]
            return [n for n in recent if any(k in n.text.casefold() for k in keys)]

        def add(kind: str, evidence: list[str]) -> None:
            found.append(HrSignal(kind, kinds[kind]["opis"], tuple(evidence), tuple(kinds[kind]["rekomendacje"][:3])))

        overload = keyword_notes("PRZECIAZENIE")
        from_notes = [f"{n.on:%d.%m.%Y}: {n.text}" for n in overload[:3]] \
            if len(overload) >= cfg["min_notatek_dla_sygnalu"] else []
        if from_notes or extra.get("PRZECIAZENIE"):
            add("PRZECIAZENIE", [*extra.get("PRZECIAZENIE", []), *from_notes])

        year_ago = today - timedelta(days=365)
        days_away = sum(max(0, (min(a.end, today) - max(a.start, year_ago)).days + 1) for a in absences if a.justified)
        if days_away >= cfg["nieobecnosc_dni_w_12_miesiacach"]:
            add("DLUGA_NIEOBECNOSC", [f"{a.start:%d.%m.%Y}–{a.end:%d.%m.%Y} ({a.kind or 'nieobecność'}, {a.days} dni)"
                                      for a in absences if a.justified and a.end >= year_ago][:3])

        changes = keyword_notes("ZMIANA_OBOWIAZKOW")
        if changes:
            add("ZMIANA_OBOWIAZKOW", [f"{n.on:%d.%m.%Y}: {n.text}" for n in changes[:2]])

        prev = cycle.previous_evaluation or employee.previous_evaluation
        current = self._current_result(cycle)
        if prev and current:
            prev_rank = self._level_rank.get((prev.level or "").casefold())
            dropped = (prev_rank is not None and self._level_rank.get(current.level.casefold(), prev_rank) < prev_rank) or \
                      (prev.outcome == Outcome.POSITIVE.value and current.outcome is Outcome.NEGATIVE)
            if dropped:
                add("SPADEK_OCEN", [f"poprzednio: {prev.outcome}, {prev.level}; teraz: {current.outcome.value}, {current.level}"])

        praise_from = today - timedelta(days=30 * cfg["okno_docenienia_miesiecy"])
        praise = [n for n in notes if n.on >= praise_from and n.sentiment is Sentiment.POSITIVE]
        if len(praise) >= cfg["min_pozytywnych_do_docenienia"]:
            add("DO_DOCENIENIA", [f"{n.on:%d.%m.%Y}: {n.text}" for n in praise[:3]])
        return found

    def hr_partner(self, cycle: EvaluationCycle, employee: Employee, notes: Sequence[Note],
                   absences: Sequence[Absence], today: date, use_ai: bool = True,
                   extra: Mapping[str, Sequence[str]] | None = None) -> HrReport:
        signals = self._detect_signals(cycle, employee, notes, absences, today, extra)
        if not signals or not use_ai:
            return HrReport(tuple(signals), "REGULY")
        pseudo = self._people(employee)
        kinds = [s.kind for s in signals]
        catalog = "\n".join(f"- {k}: {'; '.join(self.catalog.hr['sygnaly'][k]['rekomendacje'])}" for k in kinds)
        prompt = _prompt("hr", person=pseudo.token_for(employee.first_name, employee.last_name),
                         position=employee.position, catalog=catalog,
                         signals="\n".join(f"- {s.kind} | {pseudo.mask('; '.join(s.evidence))}" for s in signals))
        schema = {"type": "object", "properties": {"sygnaly": {"type": "array", "items": {
            "type": "object", "properties": {"typ": {"type": "string", "enum": kinds}, "opis": {"type": "string"},
                                             "rekomendacje": {"type": "array", "items": {"type": "string"}}},
            "required": ["typ", "opis", "rekomendacje"]}}}, "required": ["sygnaly"]}

        def validate(raw: dict) -> dict[str, tuple[str, list[str]]]:
            out = {}
            for it in raw.get("sygnaly") or []:
                kind, desc = (it or {}).get("typ"), pseudo.unmask(str((it or {}).get("opis", ""))).strip()
                if kind not in kinds or not 10 <= len(desc) <= 500:
                    continue
                recs = [pseudo.unmask(r) for r in _str_list(it.get("rekomendacje", []), 4, 300)]
                text = " ".join([desc, *recs]).casefold()
                if any(b in text for b in _BANNED_IN_HR) or _LEFTOVER_TOKEN.search(text):
                    raise AiInvalidOutput("Odpowiedź wykracza poza rolę HR partnera (diagnoza lub dane osobowe).")
                out[kind] = (desc, recs)
            if not out:
                raise AiInvalidOutput("Brak poprawnych opisów sygnałów.")
            return out

        ai = self._ask_json("hr_partner", prompt, schema, "text", validate)
        if ai is None:
            return HrReport(tuple(signals), "REGULY")
        merged = tuple(HrSignal(s.kind, ai[s.kind][0], s.evidence, tuple(ai[s.kind][1]) or s.recommendations)
                       if s.kind in ai else s for s in signals)
        return HrReport(merged, "AI")
