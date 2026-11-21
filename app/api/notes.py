"""Notes endpoints (docs/api.md): the evaluator's observations during the cycle – the evidence for the
conversation prep and the drafts. A note counts as evidence only when the evaluator tags it with a criterion
and a sentiment (manually, or by accepting a suggestion); AI suggestions are never applied automatically."""
from __future__ import annotations

from dataclasses import replace

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Response

from app.domain.cycle import EvaluationCycle, Status
from app.domain.errors import FieldLocked, NotAuthorized, NotFound, ValidationError
from app.domain.notes import Note, Sentiment

from . import assistant_mapping as m
from . import schemas as s
from .state import DemoState, NoteRecord, get_state

router = APIRouter(prefix="/api", tags=["notatki"])


# ---------------------------------------------------------------- helpers

def _cycle(st: DemoState, evaluation_id: int) -> EvaluationCycle:
    cycle = st.evaluations.cycles.get(str(evaluation_id))
    if cycle is None:
        raise NotFound(f"Nie ma oceny o identyfikatorze {evaluation_id}.")
    return cycle


def _record(st: DemoState, note_id: int) -> NoteRecord:
    r = st.notes.get(note_id)
    if r is None:
        raise NotFound(f"Nie ma notatki o identyfikatorze {note_id}.")
    return r


def _require_evaluator(cycle: EvaluationCycle, user_id: str | None) -> None:
    if user_id is not None and user_id != cycle.evaluator_id:
        raise NotAuthorized("Notatki z okresu oceny prowadzi tylko oceniający.")


def _require_open(cycle: EvaluationCycle) -> None:
    if cycle.status is Status.ACKNOWLEDGED:
        raise FieldLocked("Ocena jest zakończona – notatek z tego okresu nie można już zmieniać.")


def _criterion(cycle: EvaluationCycle, st: DemoState, code: str) -> str:
    cid = m.criterion_id(code)
    allowed = cycle.criteria_ids(st.evaluations.rules)
    if cid not in allowed:
        raise ValidationError([f"Kryterium „{code}” nie należy do tej oceny "
                               f"(dozwolone: {', '.join(m.criterion_code(c) for c in allowed)})."])
    return cid


def _out(st: DemoState, r: NoteRecord) -> s.NoteOut:
    author = st.directory.get(r.note.author_id) if r.note.author_id else None
    _, source, suggestions = m.to_classification(r.classification) if r.classification else (None, None, [])
    return s.NoteOut(
        id=int(r.note.id),
        evaluation_id=r.evaluation_id,
        autor=s.OsobaRef(id=st.employee_number(author.id), imie=author.first_name, nazwisko=author.last_name,
                         stanowisko=author.position) if author else s.OsobaRef(id=0, imie="", nazwisko=""),
        data=r.note.on,
        typ=s.TypNotatki(r.kind),
        tresc=r.note.text,
        criterion_kod=m.criterion_code(r.note.criterion_id) if r.note.criterion_id else None,
        wydzwiek=s.Wydzwiek(r.note.sentiment.value) if r.note.sentiment else None,
        widoczna_dla_ocenianego=r.visible_to_employee,
        status_klasyfikacji=r.status,
        zrodlo_sugestii=source,
        sugestie_ai=suggestions,
    )


def _classify(st: DemoState, note_id: int) -> None:
    """Background task: AI (or keyword rules when AI is off) proposes criteria; nothing is applied."""
    r = st.notes.get(note_id)
    cycle = st.evaluations.cycles.get(str(r.evaluation_id)) if r else None
    if r is None or cycle is None:
        return
    people = [p for p in (st.directory.get(cycle.employee_id), st.directory.get(cycle.evaluator_id)) if p]
    try:
        c = st.assistant.classify_note(r.note, cycle.sheet, cycle.additional_criteria, people)
    except Exception:  # noqa: BLE001 – the note stays usable; the evaluator tags it by hand
        if r.status == "W_TOKU":
            r.status = "BLAD"
        return
    r.classification = c
    if r.status == "W_TOKU":  # the evaluator may have tagged it meanwhile – then keep their choice
        r.status = c.status


# ---------------------------------------------------------------- endpoints

@router.post("/evaluations/{evaluation_id}/notes", response_model=s.NoteOut, status_code=201)
def add_note(evaluation_id: int, body: s.NoteIn, background: BackgroundTasks,
             x_user_id: str | None = Header(default=None), st: DemoState = Depends(get_state)) -> s.NoteOut:
    """Saved at once; untagged notes are classified in the background (`status_klasyfikacji: W_TOKU`)."""
    cycle = _cycle(st, evaluation_id)
    _require_evaluator(cycle, x_user_id)
    _require_open(cycle)
    cid = _criterion(cycle, st, body.criterion_kod) if body.criterion_kod else None
    note_id = next(st.note_ids)
    note = Note(str(note_id), body.data, body.tresc.strip(), author_id=x_user_id or cycle.evaluator_id,
                criterion_id=cid, sentiment=Sentiment(body.wydzwiek.value) if body.wydzwiek else None)
    r = NoteRecord(note, evaluation_id, body.typ.value, body.widoczna_dla_ocenianego,
                   status="RECZNA" if cid else "W_TOKU")
    st.notes[note_id] = r
    if not cid:
        background.add_task(_classify, st, note_id)
    return _out(st, r)


@router.get("/evaluations/{evaluation_id}/notes", response_model=list[s.NoteOut])
def list_notes(evaluation_id: int, x_user_id: str | None = Header(default=None),
               st: DemoState = Depends(get_state)) -> list[s.NoteOut]:
    """The evaluator sees all notes; the evaluated person only those marked `widoczna_dla_ocenianego`."""
    cycle = _cycle(st, evaluation_id)
    records = sorted(st.notes_of(evaluation_id), key=lambda r: (r.note.on, int(r.note.id)))
    if x_user_id is None or x_user_id == cycle.evaluator_id:
        return [_out(st, r) for r in records]
    if x_user_id == cycle.employee_id:
        return [_out(st, r) for r in records if r.visible_to_employee]
    raise NotAuthorized("Notatki z okresu oceny widzą tylko oceniający i oceniany.")


@router.patch("/notes/{note_id}", response_model=s.NoteOut)
def patch_note(note_id: int, body: s.NotePatch, x_user_id: str | None = Header(default=None),
               st: DemoState = Depends(get_state)) -> s.NoteOut:
    """Manual tagging, or `zaakceptuj_sugestie` – the only way an AI suggestion becomes evidence."""
    r = _record(st, note_id)
    cycle = _cycle(st, r.evaluation_id)
    _require_evaluator(cycle, x_user_id)
    _require_open(cycle)
    note = r.note
    if body.tresc is not None:
        if not body.tresc.strip():
            raise ValidationError(["Treść notatki nie może być pusta."])
        note = replace(note, text=body.tresc.strip())
    if body.zaakceptuj_sugestie:
        if not (r.classification and r.classification.suggestions):
            raise ValidationError(["Ta notatka nie ma sugestii do zaakceptowania."])
        top = r.classification.suggestions[0]
        sentiment = Sentiment(body.wydzwiek.value) if body.wydzwiek else top.sentiment
        if sentiment is None:
            raise ValidationError(["Sugestia nie określa wydźwięku – wybierz wydźwięk notatki."])
        note = replace(note, criterion_id=top.criterion_id, sentiment=sentiment, indicator=top.indicator)
        r.status = "ZATWIERDZONA"
    elif body.criterion_kod is not None or body.wydzwiek is not None:
        cid = _criterion(cycle, st, body.criterion_kod) if body.criterion_kod else note.criterion_id
        sentiment = Sentiment(body.wydzwiek.value) if body.wydzwiek else note.sentiment
        note = replace(note, criterion_id=cid, sentiment=sentiment, indicator=None)
        r.status = "RECZNA"
    if body.widoczna_dla_ocenianego is not None:
        r.visible_to_employee = body.widoczna_dla_ocenianego
    r.note = note
    return _out(st, r)


@router.delete("/notes/{note_id}", status_code=204)
def delete_note(note_id: int, x_user_id: str | None = Header(default=None),
                st: DemoState = Depends(get_state)) -> Response:
    r = _record(st, note_id)
    cycle = _cycle(st, r.evaluation_id)
    _require_evaluator(cycle, x_user_id)
    _require_open(cycle)
    del st.notes[note_id]
    return Response(status_code=204)
