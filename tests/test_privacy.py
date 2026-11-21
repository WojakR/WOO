"""Pseudonymisation before any text reaches a language model (app/application/privacy.py)."""
import pytest

from app.application.privacy import Pseudonymizer

PEOPLE = [
    ("Grzegorz", "Wzór"), ("Janina", "Kowalska"), ("Iwona", "Kładka"), ("Ewelina", "Próbka"),
    ("Bartłomiej", "Przełożony"), ("Miranda", "Wąsik"), ("Romuald", "Gut"), ("Adam", "Kowalik"),
    ("Marek", "Wróbel"), ("Paweł", "Nowak"), ("Olga", "Marta"), ("Roman", "Kowal"), ("Robert", "Konrad"),
]
P = Pseudonymizer(PEOPLE)
TOKEN = {f"{f} {l}": f"[OSOBA_{i}]" for i, (f, l) in enumerate(PEOPLE, start=1)}


@pytest.mark.parametrize(
    "text, expected",
    [
        # masculine nouns, with o/ó alternation and r -> rz
        ("Rozmowa z Grzegorzem Wzorem", "Rozmowa z [OSOBA_1]"),
        ("o Grzegorzu Wzorze", "o [OSOBA_1]"),
        # feminine: final -a drops, -ska adjective
        ("Pani Kowalskiej nie było", "Pani [OSOBA_2] nie było"),
        ("Spotkałem Kowalską", "Spotkałem [OSOBA_2]"),
        ("Dałem to Janinie", "Dałem to [OSOBA_2]"),
        ("Zapytałem Janinę", "Zapytałem [OSOBA_2]"),
        # k -> c, d -> dz before -e/-ie
        ("Iwonie Kładce przekazano", "[OSOBA_3] przekazano"),
        ("pani Próbce", "pani [OSOBA_4]"),
        ("Eweliny Próbki brak", "[OSOBA_4] brak"),
        ("Mirandzie Wąsik", "[OSOBA_6]"),
        ("Oldze i Marcie", "[OSOBA_11] i [OSOBA_11]"),
        # -y adjective surname, -owi, -iem
        ("Bartłomieja Przełożonego", "[OSOBA_5]"),
        ("Adamowi Kowalikowi", "[OSOBA_8]"),
        ("Wąsikiem", "[OSOBA_6]"),
        # mobile e: Marek -> Marka, Wróbel -> Wróbla, Paweł -> Pawła / Pawle
        ("Marka Wróbla", "[OSOBA_9]"),
        ("o Marku i Pawle", "o [OSOBA_9] i [OSOBA_10]"),
        ("o Robercie Konradzie", "o [OSOBA_13]"),
    ],
)
def test_inflected_names_are_masked(text, expected):
    assert P.mask(text) == expected


def test_names_typed_without_polish_letters_are_masked():
    assert P.mask("Grzegorz Wzor, Kladka, Probka, Wasik") == "[OSOBA_1], [OSOBA_3], [OSOBA_4], [OSOBA_6]"


def test_similar_surnames_get_their_own_token():
    assert P.mask("Kowalska i Kowalik i Kowal") == "[OSOBA_2] i [OSOBA_8] i [OSOBA_12]"


@pytest.mark.parametrize("text", ["zgodnie ze wzorem pisma", "gut feeling", "Adamczyk przyszedł",
                                  "Marcin z kadr"])
def test_common_words_and_other_names_stay(text):
    assert P.mask(text) == text


def test_phone_numbers_masked_dates_times_amounts_not():
    assert P.mask("tel. 600 123 456, +48 601-234-567, 22 123 45 67") == "tel. [TELEFON], [TELEFON], [TELEFON]"
    kept = "data 2026-06-10, godz. 10:30, kwota 1 250 zł, pkt 3"
    assert P.mask(kept) == kept


def test_pesel_and_email_masked_before_phone():
    assert P.mask("PESEL 85010112345, grzegorz.wzor@urzad.gov.pl") == "PESEL [PESEL], [EMAIL]"


def test_unmask_restores_base_form():
    masked = P.mask("Notatka: Janinie Kowalskiej pomógł Grzegorz Wzór")
    assert "Kowalsk" not in masked and "Wz" not in masked and "Janin" not in masked
    assert P.unmask(masked) == "Notatka: Janina Kowalska pomógł Grzegorz Wzór"


def test_known_limits_are_explicit():
    # a name typed all in lower case is not masked (capital first letter keeps "wzorem pisma" as text)
    assert P.mask("janina kowalska") == "janina kowalska"
    # another person with the same surname stem gets the known colleague's token
    assert P.mask("Kowalski") == TOKEN["Janina Kowalska"]
