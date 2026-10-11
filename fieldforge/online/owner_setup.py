"""Interactive local-only owner provisioning. Never accept secrets as CLI flags."""

import getpass
import sys

from fieldforge.online.accounts import _password
from fieldforge.online.chat_store import ChatError
from fieldforge.online.owner import otp_library


def setup_owner(store, *, recover=False):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ChatError(400, "Run owner setup in an interactive local terminal without redirecting output.")
    with store._db() as db:
        configured = db.execute("SELECT 1 FROM owner_config").fetchone() is not None
    if configured != recover:
        raise ChatError(409, "Use --recover-owner for the existing owner." if configured else "Set up the owner with --init-owner first.")
    recovery = getpass.getpass("Existing owner recovery code: ") if recover else None
    password = getpass.getpass("New owner password/passphrase (15–128 characters): ")
    confirmation = getpass.getpass("Repeat the new password: ")
    if password != confirmation:
        raise ChatError(400, "Passwords do not match. Owner credentials were not changed.")
    _password(password)
    secret = otp_library().random_base32()
    print("\nAdd a time-based, six-digit entry in your authenticator app.")
    print("Account: FieldForge / CLRYAN86 (30-second interval)")
    print("Private setup key:", secret)
    print("Do not share this key or this terminal output. No external QR service is used.")
    code = getpass.getpass("Current six-digit code from your authenticator: ")
    result = (store.owner_recover(recovery, password, secret, code) if recover
              else store.owner_bootstrap(password, secret, code))
    print("\nOwner configured: CLRYAN86 · display name King")
    print("Save this new owner recovery code privately:", result["recovery_code"])
    print("It replaces any earlier recovery code. It is required for local factor recovery.")
    print("Wait for the next authenticator code, then open /commons-owner after starting the preview.")
    print("Owner setup finished. This command has not started or publicly deployed the server.")
