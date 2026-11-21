"""Zakłada konto logowania (AUTH_MODE=session).

    python scripts/create_account.py <login> <id_pracownika|kadry> [--admin]

Hasło jest pytane w konsoli (nie trafia do historii poleceń). `id_pracownika` = identyfikator z katalogu
pracowników (np. henryk.pryncypal), `kadry` = dział kadr / administrator.
"""
import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.auth import create_account  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Zakłada konto logowania.")
    ap.add_argument("login")
    ap.add_argument("employee_id", help="id pracownika albo 'kadry'")
    ap.add_argument("--admin", action="store_true", help="uprawnienia administratora (wgląd w cały urząd)")
    args = ap.parse_args()
    password = getpass.getpass("Hasło (min. 10 znaków): ")
    if password != getpass.getpass("Powtórz hasło: "):
        print("Hasła się różnią.")
        return 1
    try:
        create_account(args.login, password, args.employee_id, admin=args.admin)
    except ValueError as e:
        print(e)
        return 1
    print(f"Założono konto {args.login}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
