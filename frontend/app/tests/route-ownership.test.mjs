// Static guards on the ownership boundaries. No server, no build -- these read the tree, and
// they run in a fraction of a second, which is the point: they are the checks that would
// otherwise only fail in production.

import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { FRONTEND, REPO } from "./support/harness.mjs";

test("Next.js never owns an /api path", () => {
  // Rule 1 of the two in next.config.ts. An App Router route handler here would shadow the
  // rewrite SILENTLY, because Next matches its own filesystem routes before consulting
  // rewrites() -- so FastAPI would stop receiving the path with nothing going red.
  assert.equal(
    existsSync(join(FRONTEND, "src", "app", "api")),
    false,
    "frontend/src/app/api exists: it would shadow the rewrite to FastAPI",
  );
});

test("the /api rewrite is verbatim and configurable", () => {
  const config = readFileSync(join(FRONTEND, "next.config.ts"), "utf8");
  assert.match(config, /source:\s*"\/api\/:path\*"/, "no /api rewrite source");
  assert.match(config, /\$\{API_UPSTREAM\}\/api\/:path\*/, "the rewrite is not verbatim");
  assert.match(config, /SYMONEURAL_API_UPSTREAM/, "the upstream is hardcoded");
});

test("every route folder is thin and delegates to an application", () => {
  // The architecture's load-bearing rule. A route that grows its own behaviour is how the
  // flat site/ collection became entangled in the first place.
  const pages = [
    join(FRONTEND, "src", "app", "page.tsx"),
    join(FRONTEND, "src", "app", "demo", "dispatchos", "page.tsx"),
  ];
  for (const page of pages) {
    const source = readFileSync(page, "utf8");
    assert.match(
      source,
      /from "@\/applications\//,
      `${page} does not import from an owning application`,
    );
    assert.ok(
      source.split("\n").length < 40,
      `${page} is ${source.split("\n").length} lines; route files stay thin`,
    );
  }
});

test("an application's internals are reached only through its index", () => {
  const appsDir = join(FRONTEND, "src", "applications");
  for (const name of readdirSync(appsDir)) {
    assert.ok(
      existsSync(join(appsDir, name, "index.ts")),
      `application ${name} has no public index.ts`,
    );
  }
  // Routes must import the folder, never a file inside it.
  for (const page of ["page.tsx", join("demo", "dispatchos", "page.tsx")]) {
    const source = readFileSync(join(FRONTEND, "src", "app", page), "utf8");
    assert.doesNotMatch(
      source,
      /from "@\/applications\/[^"]+\/(components|hooks|api|types|styles)/,
      `${page} reaches past an application's public index`,
    );
  }
});

test("the legacy frontend is untouched by this project", () => {
  // frontend/ must be self-contained: nothing here may import out of the tree into site/.
  const offenders = [];
  const walk = (dir) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name === "node_modules" || entry.name === ".next") continue;
        walk(full);
      } else if (/\.(ts|tsx|mjs|css)$/.test(entry.name)) {
        const source = readFileSync(full, "utf8");
        // A comment naming site/ is documentation; an import is a dependency.
        if (/(?:from|import|@import|url\()\s*["'][^"']*\.\.\/\.\.\/site\//.test(source)) {
          offenders.push(full);
        }
      }
    }
  };
  walk(join(FRONTEND, "src"));
  assert.deepEqual(offenders, [], "frontend/ imports from the legacy site/ tree");
});

test("the DispatchOS lifecycle map matches the store it mirrors", () => {
  // The UI transcribes store.NEXT. If the backend gains or loses a transition, this is the
  // check that notices, rather than an operator finding a button that 400s.
  const store = readFileSync(
    join(REPO, "backend", "dispatchos", "lib", "store.py"),
    "utf8",
  );
  const panel = readFileSync(
    join(FRONTEND, "src", "applications", "symoneural-dispatchos", "components", "BookingDetailPanel.tsx"),
    "utf8",
  );

  const block = store.match(/^NEXT = \{$([\s\S]*?)^\}$/m);
  assert.ok(block, "store.NEXT could not be located");

  const fromStore = {};
  for (const line of block[1].split("\n")) {
    const m = line.match(/^\s*"(\w+)":\s*\(([^)]*)\)/);
    if (!m) continue;
    fromStore[m[1]] = (m[2].match(/"(\w+)"/g) ?? []).map((s) => s.replaceAll('"', ""));
  }

  for (const [state, allowed] of Object.entries(fromStore)) {
    const row = panel.match(new RegExp(`^\\s*${state}:\\s*\\[([^\\]]*)\\]`, "m"));
    assert.ok(row, `the UI lifecycle map has no row for ${state}`);
    const fromUi = (row[1].match(/"(\w+)"/g) ?? []).map((s) => s.replaceAll('"', ""));
    assert.deepEqual(
      fromUi,
      allowed,
      `${state}: UI offers ${JSON.stringify(fromUi)}, store allows ${JSON.stringify(allowed)}`,
    );
  }
});
