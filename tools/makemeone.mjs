#!/usr/bin/env node
/**
 * makemeone -- scaffold one of anything this repository has a shape for.
 *
 *   node tools/makemeone.mjs component ravenstore    backend surface: router, models, lib, apps, docs, tests
 *   node tools/makemeone.mjs surface  ravenstore     frontend Next.js application
 *   node tools/makemeone.mjs page     ravenstore     static site page
 *   node tools/makemeone.mjs script   drain-cache    shell script with the lib preamble
 *   node tools/makemeone.mjs --list                  what it can make
 *   node tools/makemeone.mjs component x --dry-run   say what it would write; write nothing
 *
 * ## Why this exists
 *
 * Every convention in this tree was paid for. A component is `<name>/<name>.py` and not
 * `router.py` because thirty files called router.py tell you nothing in a file manager. Its
 * subdirectories are always `models/ lib/ apps/ docs/` because asymmetry is what made the
 * old tree unreadable. A script sources `lib/repo.sh` because sixteen of them resolved the
 * repository eight different ways and all but one counted parents.
 *
 * None of that survives being remembered. A generator is how a convention outlives the
 * person who learned it the hard way.
 *
 * ## It refuses rather than overwrites
 *
 * Every target is checked first and an existing file aborts the whole run before anything is
 * written. A scaffolder that half-writes over a real component is worse than no scaffolder.
 */
import { existsSync, mkdirSync, writeFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

// Walk up for the marker. Never count parents -- see scripts/lib/README.md for the eight
// spellings this replaced and what each one broke.
function repoRoot() {
  let d = dirname(fileURLToPath(import.meta.url));
  while (d !== "/") {
    if (existsSync(join(d, "backend", "server.py"))) return d;
    d = dirname(d);
  }
  throw new Error("not inside a SyMoNeuRaL checkout -- no backend/server.py above this file");
}

const ROOT = repoRoot();
// Per kind, because the constraint is different. A component becomes a PYTHON PACKAGE, so
// no hyphen -- `import gpu-governor` is a syntax error. A script and a page become
// filenames, and this tree spells those with hyphens: gpu-governor.sh, check-stale-pyc.py.
// One rule for both would either break imports or force scripts into a spelling nothing
// else here uses.
const NAME_RULE = {
  component: /^[a-z][a-z0-9_]{1,30}$/,
  surface:   /^[a-z][a-z0-9_]{1,30}$/,
  page:      /^[a-z][a-z0-9-]{1,40}$/,
  script:    /^[a-z][a-z0-9-]{1,40}$/,
};
const NAME_HELP = {
  component: "lowercase, digits and _, 2-31 chars -- it becomes a Python package",
  surface:   "lowercase, digits and _, 2-31 chars -- it becomes an import path",
  page:      "lowercase, digits and -, 2-41 chars -- it becomes a filename",
  script:    "lowercase, digits and -, 2-41 chars -- it becomes a filename",
};

const say = (s) => console.log(s);
const die = (s) => { console.error(`makemeone: ${s}`); process.exit(1); };

/** Title Case for prose, from a snake_case component name. */
const title = (n) => n.split("_").map((w) => w[0].toUpperCase() + w.slice(1)).join(" ");
/** PascalCase for TypeScript identifiers. */
const pascal = (n) => n.split(/[_-]/).map((w) => w[0].toUpperCase() + w.slice(1)).join("");

// ---------------------------------------------------------------- what each kind writes

function component(name) {
  const T = title(name);
  return {
    [`backend/${name}/__init__.py`]:
`"""${name}: the ${T} surface.

Exports the router and nothing else. Import the package, not its module, so a bare name from
here cannot shadow one in server.py.
"""
from __future__ import annotations

from .${name} import router

__all__ = ["router"]
`,
    [`backend/${name}/${name}.py`]:
`"""${T} -- routes.

Named for the component, not router.py. A directory of thirty router.py files tells you
nothing without opening one.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from core.ratelimit import throttled_for
from .models import ${pascal(name)}Request, ${pascal(name)}Result

# prefix and tags live HERE, not at the mount, so /docs groups this surface by reading the
# router rather than by server.py remembering to say so.
router = APIRouter(prefix="/api/${name}", tags=["${name}"])


@router.get("/state", response_model=${pascal(name)}Result,
            summary="What this surface can do, and what it last did")
async def state() -> ${pascal(name)}Result:
    """State is a READING, never a stored claim.

    Ask the thing; do not keep a flag beside it. A flag and the thing it describes disagree
    eventually, and the flag is always the one that gets believed.
    """
    return ${pascal(name)}Result(ok=True, detail="not implemented")


@router.post("", response_model=${pascal(name)}Result, summary="Do the thing",
             dependencies=[Depends(throttled_for("${name}"))])
async def act(body: ${pascal(name)}Request) -> ${pascal(name)}Result:
    """Bounds are enforced here and never trusted from the client.

    Out-of-range fields are CLAMPED rather than rejected -- an out-of-range value is a caller
    bug, and refusing the whole request over one is worse than correcting it. Something
    oversized hard-fails, because answering a truncated question is worse than refusing it.
    """
    raise NotImplementedError("${name}.act")
`,
    [`backend/${name}/models/__init__.py`]:
`"""Request and response models for ${T}."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ${pascal(name)}Request(BaseModel):
    """What a caller may send. Every field bounded -- an unbounded field is a denial of service."""

    text: str = Field("", max_length=4_000)


class ${pascal(name)}Result(BaseModel):
    """What this surface answers. Shaped so a failure is DATA, not an exception."""

    ok: bool
    detail: str = ""
`,
    [`backend/${name}/lib/__init__.py`]:
`"""Library for ${T}. No routes, and nothing here may have a side effect on import."""
from __future__ import annotations
`,
    [`backend/${name}/apps/__init__.py`]:
`"""Programs for ${T}: runnable, or driven by a route. Not imported by the router."""
from __future__ import annotations
`,
    [`backend/${name}/docs/.gitkeep`]: "",
    [`tests/component/${name}/test_${name}.py`]:
`"""${T}: what the surface does, not what its source says.

A test that reads source and asserts a string is a grep with a test's authority. #94 shipped
a client whose eighteen such checks were green and whose surface was dead on arrival.

PROVE the behaviour: break it on purpose, watch this fail, then fix it. A test that passes
before and after your change tested nothing.
"""
from __future__ import annotations

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ${name} import router


class ${pascal(name)}Routes(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)

    def test_state_answers(self):
        r = self.client.get("/api/${name}/state")
        self.assertEqual(r.status_code, 200)
        self.assertIn("ok", r.json())


if __name__ == "__main__":
    unittest.main()
`,
  };
}

function surface(name) {
  const P = pascal(name), T = title(name);
  return {
    [`frontend/app/src/applications/symoneural-${name}/index.ts`]:
`export { ${P}Workspace } from "./components/${P}Workspace";
export type { ${P}State } from "./types";
`,
    [`frontend/app/src/applications/symoneural-${name}/types/index.ts`]:
`export type ${P}State = {
  ok: boolean;
  detail: string;
};
`,
    [`frontend/app/src/applications/symoneural-${name}/api/client.ts`]:
`/**
 * The ${T} surface's own client. Wraps the shared one; never calls fetch directly.
 *
 * One place writes a fetch, so one place owns the timeout, the non-OK throw and the SSE
 * parse. Thirteen fetch idioms is what this replaced.
 */
import { api } from "@/lib/api/client";

import type { ${P}State } from "../types";

export function get${P}State(): Promise<${P}State> {
  return api.get<${P}State>("/api/${name}/state");
}
`,
    [`frontend/app/src/applications/symoneural-${name}/components/${P}Workspace.tsx`]:
`"use client";

import { useEffect, useState } from "react";

import { get${P}State } from "../api/client";
import type { ${P}State } from "../types";
import styles from "../styles/${name}.module.css";

export function ${P}Workspace() {
  const [state, setState] = useState<${P}State | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    get${P}State()
      .then((s) => { if (live) setState(s); })
      // The error is RENDERED, never swallowed. A surface that fails silently looks
      // identical to one that is merely slow, and the visitor waits for both.
      .catch((e: unknown) => { if (live) setError(e instanceof Error ? e.message : String(e)); });
    return () => { live = false; };
  }, []);

  if (error) return <p className={styles.error}>${T} is unavailable: {error}</p>;
  if (!state) return <p className={styles.loading}>Reading ${name}…</p>;
  return <section className={styles.root}><p>{state.detail}</p></section>;
}
`,
    [`frontend/app/src/applications/symoneural-${name}/styles/${name}.module.css`]:
`.root { display: flex; flex-direction: column; gap: var(--s2, 12px); }
.loading { color: var(--dim, #888); }
.error { color: var(--warn, #c66); }
`,
    [`frontend/app/src/app/${name}/page.tsx`]:
`import { ${P}Workspace } from "@/applications/symoneural-${name}";

// A route file imports its application's entry component and nothing else. Everything the
// surface owns lives under src/applications/symoneural-${name}/.
export default function Page() {
  return <${P}Workspace />;
}
`,
  };
}

function page(name) {
  const T = title(name);
  return {
    [`frontend/site/pages/${name}.html`]:
`<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SyMoNeuRaL ${T}</title>
<link rel="stylesheet" href="/css/symoneural.css">
</head>
<body>
<main class="wrap">
  <h1>${T}</h1>
  <!-- Nothing that can change is typed here. The chat page said "SymonChat S1-7B" through
       three model changes because it was markup. Fetch it. -->
  <p id="${name}-state">&nbsp;</p>
</main>
<script src="/js/app.js"></script>
<script src="/js/shell.js" defer></script>
<script src="/js/fit.js" defer></script>
<script>
(function () {
  'use strict';
  // api.js is the only place a fetch is written: it throws on a non-OK response, carries an
  // AbortController timeout, and sends no credential header -- there are none on this box.
  window.symoneural.api.get('/api/${name}/state')
    .then(function (s) { document.getElementById('${name}-state').textContent = s.detail; })
    .catch(function (e) { document.getElementById('${name}-state').textContent = 'unavailable: ' + e.message; });
}());
</script>
</body>
</html>
`,
  };
}

function script(name) {
  return {
    [`scripts/${name}.sh`]:
`#!/usr/bin/env bash
# ${name}.sh -- one line saying what this does TO THIS BOX.
#
# git log answers "why is the code like this". A script's header answers "what will this do
# to my machine", which is the question somebody has at 3am with a stopped service.
set -euo pipefail
. "$(dirname -- "\${BASH_SOURCE[0]}")/lib/repo.sh"
. "\$ROOT/scripts/lib/say.sh"
. "\$ROOT/scripts/lib/require.sh"

# need_root "\$@"        # uncomment if this writes outside the repository
# need_cmd jq

head_ "${name}"
run true
ok "done"
`,
  };
}

const KINDS = { component, surface, page, script };

// ---------------------------------------------------------------- the run

function main(argv) {
  if (argv.includes("--list") || argv.length === 0) {
    say("makemeone can make:");
    for (const k of Object.keys(KINDS)) say(`  ${k}`);
    say("\n  node tools/makemeone.mjs <kind> <name> [--dry-run]");
    return 0;
  }
  const dry = argv.includes("--dry-run");
  const [kind, name] = argv.filter((a) => !a.startsWith("--"));

  if (!KINDS[kind]) die(`no such kind: ${kind}. Try --list.`);
  if (!name) die(`${kind} needs a name`);
  if (!NAME_RULE[kind].test(name)) {
    die(`"${name}" is not a ${kind} name this tree uses: ${NAME_HELP[kind]}, starting with a letter.`);
  }
  if (kind === "component" && existsSync(join(ROOT, "backend", name))) {
    die(`backend/${name} already exists -- refusing. Delete it deliberately or pick another name.`);
  }

  const files = KINDS[kind](name);

  // Every target checked BEFORE anything is written. A half-written scaffold over a real
  // component is worse than no scaffolder at all.
  const clash = Object.keys(files).filter((f) => existsSync(join(ROOT, f)));
  if (clash.length) {
    die(`would overwrite ${clash.length} existing file(s), refusing:\n  ` + clash.join("\n  "));
  }

  for (const [rel, body] of Object.entries(files)) {
    const abs = join(ROOT, rel);
    if (dry) { say(`  would write  ${rel}`); continue; }
    mkdirSync(dirname(abs), { recursive: true });
    writeFileSync(abs, body);
    if (rel.endsWith(".sh")) mkdirSync(dirname(abs), { recursive: true });
    say(`  ${rel}`);
  }
  if (dry) { say(`\n  ${Object.keys(files).length} files. Nothing written.`); return 0; }

  say(`\n  ${Object.keys(files).length} files written. Next:`);
  if (kind === "component") {
    say(`    1. mount it in backend/server.py:  app.include_router(${name}.router)`);
    say(`    2. add its budget to LIMITS in backend/core/config.py`);
    say(`    3. python3 tools/build/build_component_readmes.py`);
    say(`    4. python3 -m pytest tests/component/${name} -q`);
    say(`    5. write the prose half of backend/${name}/README.md -- the generator cannot`);
  } else if (kind === "surface") {
    say(`    1. cd frontend/app && npm run dev   ->  http://localhost:3000/${name}`);
    say(`    2. add a slice test under frontend/app/tests/`);
  } else if (kind === "page") {
    say(`    1. python3 tools/build/build_cachebust.py`);
    say(`    2. sudo scripts/deploy.sh`);
  } else if (kind === "script") {
    say(`    1. chmod +x scripts/${name}.sh`);
    say(`    2. bash -n scripts/${name}.sh`);
  }
  return 0;
}

process.exit(main(process.argv.slice(2)));
