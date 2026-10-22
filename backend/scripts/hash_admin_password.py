"""Generate a bcrypt hash for the ADMIN_PASSWORD_HASH environment variable.

Usage (run locally; nothing is sent anywhere, the password is never echoed or stored):
    python3 backend/scripts/hash_admin_password.py            # type a password twice
    python3 backend/scripts/hash_admin_password.py --generate # create a strong random one

Put the printed hash in the server's ADMIN_PASSWORD_HASH setting (e.g. Vercel → home-genies-api →
Settings → Environment Variables) and remove ADMIN_PASSWORD. On the next request/startup the admin
account takes the new credential and every older admin session is signed out.
Uses the same bcrypt scheme as backend/core.py (bcrypt.hashpw with a fresh gensalt()).
"""
import getpass
import secrets
import string
import sys

import bcrypt


def strong_enough(pw: str) -> bool:
    return (len(pw) >= 14 and any(c.islower() for c in pw) and any(c.isupper() for c in pw)
            and any(c.isdigit() for c in pw) and any(c in "!@#$%^&*-_=+?" for c in pw))


def generate(length: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*-_=+?"
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        if strong_enough(pw):
            return pw


def main() -> int:
    if "--generate" in sys.argv:
        pw = generate()
        print("New admin password (store it in a password manager now; it is shown only once):")
        print("  " + pw)
    else:
        pw = getpass.getpass("New admin password: ")
        if getpass.getpass("Repeat password: ") != pw:
            print("Passwords do not match.", file=sys.stderr)
            return 1
        if not strong_enough(pw):
            print("Too weak: use 14+ characters with upper, lower, digit and a symbol (!@#$%^&*-_=+?).", file=sys.stderr)
            return 1
    print("\nADMIN_PASSWORD_HASH=" + bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
