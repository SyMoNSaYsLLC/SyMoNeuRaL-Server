// The migrated vertical slice, exercised against a real Next production server and a real
// DispatchOS API. Nothing here talks to the live service: both processes are started on
// kernel-assigned ports, the store is a throwaway temp file, and both are stopped in `after`.
//
// What this DOES prove: the route is served, the preview carries its robots directives, the
// /api rewrite reaches FastAPI without Next shadowing it, the tier boundaries hold, and the
// six v1 workflows -- intake, quote, driver assignment and dispatch, reminder, review request
// -- run end to end through the same contract the browser client uses.
//
// What it does NOT prove, and no assertion here should be read as implying: responsive
// rendering, visual parity with site/, or anything requiring a real browser. Those need a
// browser run and are recorded as outstanding in ops/docs/FRONTEND-ROUTE-OWNERSHIP.md.
//
// ## Why the API is exercised DIRECTLY and not through the Next rewrite
//
// Measured, not assumed: `rewrites()` is evaluated by `next build` and its destination is
// written into `.next/routes-manifest.json`. `next start` serves that manifest, so
// SYMONEURAL_API_UPSTREAM has no effect at run time -- an earlier draft of this file set it
// when starting the server and every /api call went to the DEFAULT upstream instead, which on
// this box is the live API on :8800. Sending fixture credentials through a proxy whose
// destination is fixed at build time is how a test suite ends up authenticating against
// production, so it is not done: the contract is exercised against the fixture's own origin,
// and only the page itself is fetched through Next.

import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import {
  FIXTURE_PASSWORD,
  FRONTEND,
  makeClient,
  startFixtureApi,
  startNextServer,
} from "./support/harness.mjs";

let api;
let next;

before(async () => {
  api = await startFixtureApi();
  next = await startNextServer(api.origin);
}, { timeout: 180_000 });

after(async () => {
  await next?.stop();
  await api?.stop();
});

// ---------------------------------------------------------------- the route itself

test("/demo/dispatchos is served by Next and is a workspace, not a landing page", async () => {
  const response = await fetch(`${next.origin}/demo/dispatchos`);
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /DispatchOS/, "the page does not name the application");
  // The shell must actually be there -- rail, header and workspace, not a marketing hero.
  assert.match(html, /Transport dispatch/, "the application header eyebrow is missing");
});

test("the Donnie preview is noindex, nofollow and noarchive", async () => {
  const response = await fetch(`${next.origin}/demo/dispatchos`);
  const html = await response.text();
  const robots = html.match(/<meta name="robots" content="([^"]+)"/);
  assert.ok(robots, "no robots meta tag on the preview");
  for (const directive of ["noindex", "nofollow", "noarchive"]) {
    assert.match(robots[1], new RegExp(directive), `robots is missing ${directive}`);
  }
});

// ---------------------------------------------------------------- the API boundary

test("the fixture is a fixture, and never the live store", async () => {
  // The guard that makes every assertion below safe to run. If this ever sees the four real
  // account names, something is pointed at run/dispatchos.db and the suite must not proceed.
  const status = await fetch(`${api.origin}/api/dispatchos/status`);
  assert.equal(status.status, 200);
  const board = await fetch(`${api.origin}/api/dispatchos/board`);
  assert.equal(board.status, 401, "the fixture answered a board to an anonymous caller");
});

test("Next serves the page and claims no /api route of its own", async () => {
  // The shadowing question, asked the only way that is safe here. Next must not ANSWER an
  // /api path from its own filesystem routes; that it forwards one is a property of the
  // build-time rewrite and of Caddy in production, both asserted in route-ownership.test.mjs.
  const page = await fetch(`${next.origin}/demo/dispatchos`);
  assert.equal(page.status, 200);
  const notFound = await fetch(`${next.origin}/api/__definitely_not_a_route__`, {
    redirect: "manual",
  });
  assert.notEqual(
    notFound.status,
    200,
    "Next answered an /api path itself; a route handler is shadowing FastAPI",
  );
});

test("dispatch responses are not cacheable", async () => {
  const response = await fetch(`${api.origin}/api/dispatchos/status`);
  assert.match(
    response.headers.get("cache-control") ?? "",
    /no-store/,
    "a named customer's dispatch data must not be reusable from a cache",
  );
});

// ---------------------------------------------------------------- authentication boundaries

test("an anonymous caller gets 401, not a board", async () => {
  const anon = makeClient(api.origin);
  const board = await anon.call("/api/dispatchos/board");
  assert.equal(board.status, 401);
  assert.equal(board.json?.detail, "sign in to use DispatchOS");
});

test("a customer cannot reach an operator action", async () => {
  const rider = makeClient(api.origin);
  const login = await rider.call("/api/dispatchos/login", {
    method: "POST",
    body: { username: "fixture-rider", password: FIXTURE_PASSWORD },
  });
  assert.equal(login.status, 200);
  assert.equal(login.json.user.role, "customer");

  assert.equal((await rider.call("/api/dispatchos/drivers")).status, 403);
  assert.equal(
    (await rider.call("/api/dispatchos/rules")).status,
    403,
    "a customer read the operator's rate rules",
  );
});

test("a wrong password and an unknown user are answered identically", async () => {
  const a = makeClient(api.origin);
  const b = makeClient(api.origin);
  const wrong = await a.call("/api/dispatchos/login", {
    method: "POST",
    body: { username: "fixture-operator", password: "not-the-right-passphrase" },
  });
  const unknown = await b.call("/api/dispatchos/login", {
    method: "POST",
    body: { username: "nobody-at-all", password: "not-the-right-passphrase" },
  });
  assert.equal(wrong.status, 401);
  assert.equal(unknown.status, 401);
  assert.equal(
    wrong.json.detail,
    unknown.json.detail,
    "a different answer for an unknown user is a username oracle",
  );
});

// ---------------------------------------------------------------- the v1 workflow

test("intake, quote, driver assignment, reminder and review run end to end", async () => {
  const op = makeClient(api.origin);
  const login = await op.call("/api/dispatchos/login", {
    method: "POST",
    body: { username: "fixture-operator", password: FIXTURE_PASSWORD },
  });
  assert.equal(login.status, 200, `operator login: ${login.status} ${login.text}`);
  assert.equal(login.json.user.role, "operator");

  // --- basic intake
  const created = await op.call("/api/dispatchos/bookings", {
    method: "POST",
    body: {
      rider: "Slice Test",
      contact: "slice@example.invalid",
      pickup: "Terminal 2",
      dropoff: "Old Town",
      when_text: "tomorrow, 09:00",
      passengers: 2,
      luggage: 1,
      notes: "",
    },
  });
  assert.equal(created.status, 201);
  const id = created.json.booking.id;
  assert.equal(created.json.booking.state, "requested");

  // --- a driver to assign
  const driver = await op.call("/api/dispatchos/drivers", {
    method: "POST",
    body: { name: "Slice Driver", vehicle: "Saloon" },
  });
  assert.equal(driver.status, 201);
  const driverId = driver.json.driver.id;

  // --- quote. With no rate rules configured this MUST carry no figure: the customer preview
  //     promises in writing that it carries no pricing of any kind, and a placeholder number
  //     here would be the product inventing the one thing that document rules out.
  const quoted = await op.call(`/api/dispatchos/bookings/${id}/quote`, {
    method: "POST",
    body: { distance_km: null },
  });
  assert.equal(quoted.status, 200);
  assert.equal(quoted.json.booking.state, "quoted");
  assert.equal(
    quoted.json.booking.quote.estimate,
    null,
    "a quote produced a figure with no rate rules configured",
  );

  // --- confirm, then dispatch WITH the driver: assignment rides on the dispatch call.
  assert.equal(
    (await op.call(`/api/dispatchos/bookings/${id}/advance`, {
      method: "POST",
      body: { to: "confirmed", driver_id: null, detail: "" },
    })).status,
    200,
  );
  const dispatched = await op.call(`/api/dispatchos/bookings/${id}/advance`, {
    method: "POST",
    body: { to: "dispatched", driver_id: driverId, detail: "" },
  });
  assert.equal(dispatched.status, 200);
  assert.equal(dispatched.json.booking.driver.name, "Slice Driver");

  // --- an out-of-order move is refused by the store, not by the UI hiding a button
  const illegal = await op.call(`/api/dispatchos/bookings/${id}/advance`, {
    method: "POST",
    body: { to: "requested", driver_id: null, detail: "" },
  });
  assert.equal(illegal.status, 400);

  // --- reminder. Composed, stored, shown -- and never sent.
  const reminder = await op.call(`/api/dispatchos/bookings/${id}/message`, {
    method: "POST",
    body: { kind: "reminder" },
  });
  assert.equal(reminder.status, 201);
  assert.equal(reminder.json.message.sent_at, null, "a message claimed to have been sent");
  assert.match(reminder.json.delivery, /not sent/);

  // --- complete, then the review request
  assert.equal(
    (await op.call(`/api/dispatchos/bookings/${id}/advance`, {
      method: "POST",
      body: { to: "completed", driver_id: null, detail: "" },
    })).status,
    200,
  );
  const review = await op.call(`/api/dispatchos/bookings/${id}/message`, {
    method: "POST",
    body: { kind: "review_request" },
  });
  assert.equal(review.status, 201);
  assert.equal(review.json.message.sent_at, null);

  const finished = await op.call(`/api/dispatchos/bookings/${id}/advance`, {
    method: "POST",
    body: { to: "reviewed", driver_id: null, detail: "" },
  });
  assert.equal(finished.status, 200);
  assert.equal(finished.json.booking.state, "reviewed");

  // The record trail is append-only and carries every step that happened -- INCLUDING the two
  // compositions, which is why `message` appears between the lifecycle rows. That is the
  // trail doing its job: "a reminder was composed for this job" is part of what happened to
  // it, and an operator answering "what did we do about this booking" needs to see it.
  const kinds = finished.json.booking.events.map((e) => e.kind);
  assert.deepEqual(kinds, [
    "requested",
    "quoted",
    "confirmed",
    "dispatched",
    "message",
    "completed",
    "message",
    "reviewed",
  ]);
  assert.equal(
    kinds.filter((k) => k === "message").length,
    2,
    "the reminder and the review request are not both recorded in the trail",
  );
});

test("a customer sees only their own trips", async () => {
  const rider = makeClient(api.origin);
  await rider.call("/api/dispatchos/login", {
    method: "POST",
    body: { username: "fixture-rider", password: FIXTURE_PASSWORD },
  });
  const board = await rider.call("/api/dispatchos/board");
  assert.equal(board.status, 200, `rider board: ${board.status} ${board.text}`);
  // The operator's trip above is not this customer's, and the isolation is server-side.
  assert.equal(board.json.bookings.length, 0, "a customer saw a trip that is not theirs");
  assert.deepEqual(board.json.drivers, [], "a customer was given the driver roster");
});

// ---------------------------------------------------------------- no protected exposure

test("no credential or internal path is compiled into the browser bundle", () => {
  const dir = join(FRONTEND, ".next", "static");
  const bad = [];
  const walk = (d) => {
    for (const entry of readdirSync(d, { withFileTypes: true })) {
      const full = join(d, entry.name);
      if (entry.isDirectory()) {
        walk(full);
        continue;
      }
      if (!/\.(js|css|map)$/.test(entry.name)) continue;
      if (statSync(full).size > 8_000_000) continue;
      const text = readFileSync(full, "utf8");
      if (text.includes(FIXTURE_PASSWORD)) bad.push(`${full}: fixture password`);
      if (text.includes("/home/google")) bad.push(`${full}: absolute host path`);
      if (text.includes("dispatchos-logins")) bad.push(`${full}: credential file name`);
      if (/\$2a\$\d\d\$/.test(text)) bad.push(`${full}: bcrypt hash`);
    }
  };
  walk(dir);
  assert.deepEqual(bad, [], "protected information reached a browser artifact");
});
