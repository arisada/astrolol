"""Recovery CLI: python -m astrolol.plugins.security {list|set-password|add-admin|reset}

Edits the security file directly, so it works when nobody can sign in. Run it as
the user astrolol runs as, then restart astrolol.
"""
from __future__ import annotations

import argparse
import getpass
import sys

from astrolol.config.settings import settings
from astrolol.plugins.security.models import MIN_PASSWORD, USERNAME_RE
from astrolol.plugins.security.passwords import hash_password
from astrolol.plugins.security.store import SecurityStore, UserRecord, now


def _ask_password() -> str:
    pw = getpass.getpass("New password: ")
    if len(pw) < MIN_PASSWORD:
        sys.exit(f"The password needs at least {MIN_PASSWORD} characters.")
    if pw != getpass.getpass("Again: "):
        sys.exit("The passwords differ.")
    return pw


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m astrolol.plugins.security", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="show the users")
    for cmd, text in (("set-password", "change a user's password"), ("add-admin", "create (or reset) an admin")):
        p = sub.add_parser(cmd, help=text)
        p.add_argument("name")
    sub.add_parser("reset", help="delete every user, token and session: the API is open again")
    args = ap.parse_args(argv)

    store = SecurityStore(settings.security_file)
    if args.cmd == "list":
        for name, rec in store.users():
            print(f"{name}\t{rec.level}")
    elif args.cmd == "reset":
        for name, _ in store.users():
            store.delete_user(name)
        for tok in store.tokens():
            store.delete_token(tok.id)
        print("All users removed: authentication is off until the first account is created.")
    else:
        if not USERNAME_RE.match(args.name):
            sys.exit("Invalid user name.")
        found = store.get_user(args.name)
        if args.cmd == "set-password" and found is None:
            sys.exit("No such user.")
        hashed = hash_password(_ask_password())
        level = found[1].level if found and args.cmd == "set-password" else "admin"
        created = found[1].created if found else now().isoformat()
        store.put_user(found[0] if found else args.name,
                       UserRecord(password_hash=hashed, level=level, created=created))
        store.drop_sessions(args.name)
        print(f"{args.name} is now {level}.")


if __name__ == "__main__":
    main()
