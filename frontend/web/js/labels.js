// Polish labels for API enums (presentation only – no rules here).

export const STAGES = [
  { status: "KRYTERIA_DO_WYZNACZENIA", label: "Wyznaczenie kryteriów i rozmowa rozpoczynająca", short: "Wyznaczenie kryteriów" },
  { status: "KRYTERIA_DO_POTWIERDZENIA", label: "Potwierdzenie kryteriów przez ocenianego", short: "Potwierdzenie kryteriów" },
  { status: "OKRES_OCENY", label: "Okres oceny (zbieranie obserwacji)", short: "Okres oceny" },
  { status: "ROZMOWA_OCENIAJACA", label: "Rozmowa oceniająca i sporządzenie oceny", short: "Rozmowa i sporządzenie oceny" },
  { status: "OCENA_DO_ZAPOZNANIA", label: "Zapoznanie się z oceną", short: "Zapoznanie się z oceną" },
];

export const STATUS_LABEL = {
  KRYTERIA_DO_WYZNACZENIA: "Wyznaczenie kryteriów",
  KRYTERIA_DO_POTWIERDZENIA: "Potwierdzenie kryteriów",
  OKRES_OCENY: "Okres oceny",
  ROZMOWA_OCENIAJACA: "Rozmowa i sporządzenie oceny",
  OCENA_DO_ZAPOZNANIA: "Zapoznanie się z oceną",
  ZAKONCZONA: "Zakończona",
  SPRZECIW: "Sprzeciw w toku",
  ANULOWANA: "Anulowana",
};

export function stageIndex(status) {
  if (status === "ZAKONCZONA") return STAGES.length; // all done
  const i = STAGES.findIndex((s) => s.status === status);
  return i < 0 ? 0 : i;
}

export const LEVEL_LABEL = {
  ZNACZNIE_PONIZEJ: "znacznie poniżej oczekiwań",
  PONIZEJ: "poniżej oczekiwań",
  NA_POZIOMIE: "na poziomie oczekiwań",
  POWYZEJ: "powyżej oczekiwań",
  ZNACZNIE_POWYZEJ: "znacznie powyżej oczekiwań",
};

export const SCALE_SHORT = { 1: "znacznie poniżej", 3: "poniżej", 5: "na poziomie", 7: "powyżej", 9: "znacznie powyżej" };

export const ACTION_LABEL = {
  ZATWIERDZ_KRYTERIA: "Zatwierdź kryteria i przekaż ocenianemu",
  POTWIERDZ_KRYTERIA: "Potwierdzam zapoznanie z kryteriami",
  ROZPOCZNIJ_ROZMOWE: "Rozpocznij rozmowę oceniającą",
  ZATWIERDZ_OCENE: "Zatwierdź ocenę i przekaż do zapoznania",
  POTWIERDZ_ZAPOZNANIE: "Potwierdzam zapoznanie się z oceną",
  FIKCJA_ZAPOZNANIA: "Stwierdź fikcję zapoznania",
};

export const ACTION_DONE = {
  ZATWIERDZ_KRYTERIA: "Kryteria zatwierdzone i przekazane ocenianemu.",
  POTWIERDZ_KRYTERIA: "Potwierdzono zapoznanie z kryteriami.",
  ROZPOCZNIJ_ROZMOWE: "Rozpoczęto etap rozmowy oceniającej.",
  ZATWIERDZ_OCENE: "Ocena zatwierdzona i przekazana do zapoznania.",
  POTWIERDZ_ZAPOZNANIE: "Potwierdzono zapoznanie się z oceną.",
};

export const WHO_LABEL = { OCENIAJACY: "oceniający", OCENIANY: "oceniany", KADRY: "kadry", NIKT: "–" };

export const EMPLOYMENT_LABEL = { PRACOWNIK: "Pracownik służby cywilnej", URZEDNIK: "Urzędnik służby cywilnej" };

export const SIGNAL_LABEL = {
  PRZECIAZENIE: "Możliwe przeciążenie",
  DLUGA_NIEOBECNOSC: "Długa nieobecność",
  ZMIANA_OBOWIAZKOW: "Zmiana zakresu obowiązków",
  SPADEK_OCEN: "Wynik niższy niż poprzednio",
  DO_DOCENIENIA: "Warto docenić",
};

export function personName(o) {
  return o ? `${o.imie} ${o.nazwisko}`.trim() : "–";
}
