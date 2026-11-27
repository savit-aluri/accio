"""Small admin commands.

    python manage.py add-friend "Maya"            # prints Maya's invite code
    python manage.py add-friend "Sam" --cap 2.00  # a bigger daily cap for one person
    python manage.py friends                      # list friends and codes
    python manage.py usage                        # what each friend spent, last 7 days
"""

from __future__ import annotations

import argparse
import re
import secrets
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FRIENDS = ROOT / "friends.toml"
EXAMPLE = ROOT / "friends.example.toml"
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I/L to misread


def new_code(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "", name.lower())[:12] or "friend"
    return f"{slug}-" + "".join(secrets.choice(ALPHABET) for _ in range(6))


def add_friend(name: str, cap: float | None) -> None:
    if not FRIENDS.exists():
        FRIENDS.write_text(EXAMPLE.read_text())
    config = tomllib.loads(FRIENDS.read_text())
    if any(f.get("name", "").lower() == name.lower() for f in config.get("friends", [])):
        sys.exit(f"{name} is already in friends.toml.")
    code = new_code(name)
    name_toml = name.replace("\\", "\\\\").replace('"', '\\"')
    block = f'\n[[friends]]\nname = "{name_toml}"\ncode = "{code}"\n'
    if cap is not None:
        block += f"daily_cap = {cap:.2f}\n"
    with FRIENDS.open("a") as fh:
        fh.write(block)
    print(f"Added {name}. Their invite code is: {code}")
    print("Restart the server so it picks up the change.")


def list_friends() -> None:
    config = tomllib.loads(FRIENDS.read_text()) if FRIENDS.exists() else {}
    per = config.get("limits", {}).get("daily_cap_per_friend", 1.0)
    for f in config.get("friends", []):
        state = "" if f.get("active", True) else "  (turned off)"
        print(f"{f['name']:<16} {f['code']:<22} ${float(f.get('daily_cap', per)):.2f}/day{state}")


def usage() -> None:
    sys.path.insert(0, str(ROOT))
    from accio.settings import Settings
    from accio.store import Database, SpendLedger

    settings = Settings.load()
    ledger = SpendLedger(Database(settings.data_dir / "accio.db", settings.database_url), settings.timezone)
    rows = ledger.report()
    if not rows:
        print("No searches yet.")
    for row in rows:
        print(f"{row['day']}  {row['friend']:<16} {row['searches']:>3} searches  ${row['dollars']:.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Accio admin")
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add-friend", help="Create an invite code")
    add.add_argument("name")
    add.add_argument("--cap", type=float, help="Daily cap in dollars for this person")
    sub.add_parser("friends", help="List friends and codes")
    sub.add_parser("usage", help="Spending per friend")
    args = parser.parse_args()
    if args.command == "add-friend":
        add_friend(args.name, args.cap)
    elif args.command == "friends":
        list_friends()
    else:
        usage()


if __name__ == "__main__":
    main()
