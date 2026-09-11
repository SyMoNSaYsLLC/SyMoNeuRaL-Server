"""No client of ours sends a credential header, because nothing here reads one.

## What this file used to be

Twenty tests pinning `X-Symoneural-Token` and the name it replaced: every reader, every
fallback, the case-insensitive match, which name won when both were present, and a tripwire
for a reader that had only half of it. Written because a credential name is agreed between a
sender and a reader that never import each other, so a rename could be applied to one side,
pass every test, and 401 an operator whose token was correct.

**Every reader is gone.** Owner decision, 2026-09-11, ending *"i will never reverse the
decision"* and *"KILL ALL THE FUCKING TOKEN REQUEST, REQUIREMENTS, FIELDS ETC"*. Testing the
agreement between senders and readers of a header nothing reads is testing nothing.

Deleted rather than quarantined, for the reason `test_no_tokens.py` gives: the decision
removes the only argument for keeping them. What deletion leaves is a hole on the **sending**
side — nothing then stops a client growing a credential header against a server that will
ignore it, which is a silent failure in the direction hardest to notice.

This file is that guard, pointed the other way.

## Why sending one is worth catching

A client that sends a credential the server ignores looks exactly like a client that is
authenticated. It works, so nobody questions it, and the first time anybody finds out is when
that header is presumed to be doing something.

It is also a leak: `api.js` is served to every visitor, and a credential in a request it
builds is a credential in the browser's network tab.

The session cookie is NOT a credential header and is not caught here. Nobody types it, no
caller presents it to be let in, and it is what makes a session unforgeable — see
`frontend/app/src/lib/auth/README.md`.
"""
from __future__ import annotations

import pathlib
import re
import unittest

ROOT = next(_p for _p in pathlib.Path(__file__).resolve().parents
            if (_p / "backend" / "server.py").is_file())

#: Where a first-party client builds a request. Not a glob: vendored code is not ours to
#: police, and a glob would have swept `.venv` the moment one appeared.
CLIENT_SOURCES = [
    ROOT / "frontend" / "site" / "js",
    ROOT / "frontend" / "app" / "src" / "lib" / "api",
    ROOT / "bin" / "symoneural-cli",
]

#: Header names that mean "I am presenting a credential to be let in". `Cookie` is absent
#: deliberately -- see the module docstring.
CREDENTIAL_HEADERS = re.compile(
    r"""['"]\s*(authorization|x-api-key|x-auth-token|x-access-token|"""
    r"""x-symoneural-token|x-sym-token|x-reinforce-token|x-operator-token)\s*['"]""",
    re.IGNORECASE)

#: `Authorization: Bearer` built without the literal header name.
BEARER = re.compile(r"""['"]\s*bearer\s""", re.IGNORECASE)


def _sources() -> list[pathlib.Path]:
    out: list[pathlib.Path] = []
    for s in CLIENT_SOURCES:
        if s.is_file():
            out.append(s)
        elif s.is_dir():
            out += [p for p in sorted(s.rglob("*"))
                    if p.is_file() and p.suffix in {".js", ".ts", ".mjs", ".py", ""}]
    return out


class NoClientSendsACredential(unittest.TestCase):
    def test_no_first_party_client_names_a_credential_header(self):
        offenders = []
        for p in _sources():
            text = p.read_text(encoding="utf-8", errors="replace")
            for pattern, what in ((CREDENTIAL_HEADERS, "credential header"), (BEARER, "bearer scheme")):
                for m in pattern.finditer(text):
                    line = text[:m.start()].count("\n") + 1
                    # A comment saying we do NOT send one is the documentation this rule
                    # wants, not a violation of it.
                    body = text.splitlines()[line - 1].strip()
                    if body.startswith(("*", "//", "#", "/*")):
                        continue
                    offenders.append(f"{p.relative_to(ROOT)}:{line}  {what}  {body[:70]}")
        self.assertEqual(offenders, [],
                         "a first-party client sends a credential the server does not read:\n  "
                         + "\n  ".join(offenders))

    def test_the_walk_found_client_code(self):
        """Non-vacuous. An empty source list would make the check above pass over nothing --
        which is exactly how the token guard passed for days while walking a directory that
        had stopped existing."""
        found = _sources()
        self.assertGreater(len(found), 5,
                           f"found only {len(found)} client files; CLIENT_SOURCES is stale")
        self.assertTrue(any(p.name == "api.js" for p in found),
                        "frontend/site/js/api.js is the shared client and must be scanned")


if __name__ == "__main__":
    unittest.main()
