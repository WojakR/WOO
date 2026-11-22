"""backend.llm always pseudonymises: no name, PESEL, e-mail or phone from the text reaches the model."""
import json

import pytest

from backend import llm

NOTE = "Notatka: Grzegorzowi Wzorowi i Janinie Kowalskiej, tel. 600 123 456, PESEL 85010112345, gw@urzad.gov.pl"
LEAKS = ("Grzeg", "Wzor", "Wzór", "Janin", "Kowalsk", "600 123 456", "85010112345", "@")


class Recorder(list):
    """Records what would leave the application; `answer` is what the fake model replies."""

    answer = "ok"

    def __call__(self, system, prompt, json_mode, temperature):
        self.append({"system": system, "prompt": prompt})
        return self.answer


@pytest.fixture
def sent(monkeypatch):
    """Real (non-mock) path with the network call replaced."""
    rec = Recorder()
    monkeypatch.setattr(llm.config, "LLM_MOCK", False)
    monkeypatch.setattr(llm, "_complete", rec)
    return rec


def token(first, last):
    return llm._guard().token_for(first, last)


def test_mock_echo_shows_only_tokens():
    answer = llm.ask_llm(NOTE)  # tests run with LLM_MOCK=1
    assert answer.startswith("[MOCK]")
    assert token("Grzegorz", "Wzór") in answer and "[TELEFON]" in answer and "[PESEL]" in answer
    assert not any(leak in answer for leak in LEAKS)


def test_nothing_personal_reaches_the_model_and_names_come_back(sent):
    sent.answer = f"Rozmowa z {token('Grzegorz', 'Wzór')} przebiegła dobrze."
    answer = llm.ask_llm(NOTE, system="Pomagasz Janinie Kowalskiej.")
    out = sent[0]["system"] + sent[0]["prompt"]
    assert not any(leak in out for leak in LEAKS)
    assert answer == "Rozmowa z Grzegorz Wzór przebiegła dobrze."


def test_tokens_of_the_assistant_are_left_alone(sent):
    # assistant.py pseudonymises with its own [OSOBA_n] numbering; the guard must neither restore nor confuse them
    sent.answer = "[OSOBA_1] wykonał zadanie."
    assert llm.ask_llm("Oceń [OSOBA_1].") == "[OSOBA_1] wykonał zadanie."
    assert sent[0]["prompt"] == "Oceń [OSOBA_1]."


def test_extra_people_outside_the_directory(sent):
    llm.ask_llm("Zenon Testowy przyszedł z Zenonem Testowym.", people=[("Zenon", "Testowy")])
    assert "Zenon" not in sent[0]["prompt"] and "Testow" not in sent[0]["prompt"]


def test_json_answer_gets_names_back(sent):
    sent.answer = json.dumps({"osoba": token("Janina", "Kowalska")})
    assert llm.ask_llm_json("Kto to Janina Kowalska?") == {"osoba": "Janina Kowalska"}
    assert "Kowalsk" not in sent[0]["prompt"]

