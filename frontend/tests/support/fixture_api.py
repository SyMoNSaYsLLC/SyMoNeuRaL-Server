#!/usr/bin/env python3
"""An isolated DispatchOS API for the frontend slice test. Never the live service.

Why a fixture rather than the running API on :8800:

  - the live store is a named customer's real bookings, and a test that creates trips in it
    is a test that corrupts the thing it is checking;
  - the slice test needs to sign in, which means knowing a password, and the live passwords
    are Garrett's and were handed over out of band;
  - `backend/api.py` boots the whole box -- engines, the governor, the rack -- and none of
    that is under test here.

So this mounts the REAL routers (`apps.dispatchos.router` and `ui_router`, the same objects
`backend/api.py` mounts) against a throwaway SQLite file, exactly as
`backend/apps/test_dispatchos.py` does. The contract under test is real; only the data and
the process are disposable.

    python3 fixture_api.py --port 8811 --db /tmp/x/d.db

Prints `FIXTURE READY <port>` on stdout once uvicorn is serving, so the caller can wait for a
line instead of sleeping.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys
import threading

# The seeded password.
#
# It must clear the 15-character floor added in `fix(dispatchos): complete and secure the v1
# workflow`, AND share no substring with either username -- `validate_password` refuses "the
# password contains your account identifier", which is why the obvious
# "fixture-operator-passphrase" was rejected outright when this fixture was first written.
# That refusal is the policy working; the fixture moved rather than the rule.
#
# The slice test greps the built bundle for this exact string to prove it never reaches a
# browser artifact, so it is deliberately distinctive.
FIXTURE_PASSWORD = "lantern-quartz-meridian-8811"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--db", required=True)
    args = ap.parse_args()

    root = pathlib.Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root / "backend"))

    os.environ["SYMONEURAL_DISPATCHOS_DB"] = args.db
    os.environ["SYMONEURAL_DISPATCHOS_ENABLED"] = "1"

    import uvicorn
    from fastapi import FastAPI

    from apps import dispatchos
    from apps.dispatchos import store

    store.init_db()
    # `seed_demo_users` is not used: it only knows the four real account names, and seeding
    # those here would put a password this file contains next to a username somebody might
    # later confuse with the live one. The fixture pair is named for what it is.
    have = {u["username"] for u in store.list_users()}
    if "fixture-operator" not in have:
        store.create_user("fixture-operator", FIXTURE_PASSWORD, "operator", "Fixture operator")
    if "fixture-rider" not in have:
        store.create_user("fixture-rider", FIXTURE_PASSWORD, "customer", "Fixture rider")

    app = FastAPI()
    app.include_router(dispatchos.router, prefix="/api/dispatchos")
    app.include_router(dispatchos.ui_router)

    config = uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="warning")
    server = uvicorn.Server(config)

    def announce() -> None:
        while not server.started:
            if server.should_exit:
                return
        print(f"FIXTURE READY {args.port}", flush=True)

    threading.Thread(target=announce, daemon=True).start()
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
