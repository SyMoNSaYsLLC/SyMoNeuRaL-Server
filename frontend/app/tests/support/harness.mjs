// Process orchestration for the slice test: an isolated DispatchOS API, and the Next
// production server pointed at it.
//
// Nothing here touches the live service. The fixture binds an ephemeral port on loopback and
// `next start` binds another; both are killed in the test's `after` hook, and both are chosen
// by asking the kernel for a free port rather than by picking a number and hoping.

import { spawn } from "node:child_process";
import { createServer } from "node:net";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";

export const HERE = fileURLToPath(new URL(".", import.meta.url));
export const FRONTEND = join(HERE, "..", "..");

// The repository root, found by walking for a marker rather than by counting
// parents. `join(FRONTEND, "..")` is `frontend/`, one level short, so every path
// built from it came out as `frontend/backend/...` -- and because the only
// consumer read a file that had *also* moved, the failure named two wrong things
// at once and looked like a missing file rather than a wrong root. Counting
// parents fails exactly this way: the wrong directory usually exists.
function repoRoot(from) {
  for (let dir = from; ; dir = dirname(dir)) {
    if (existsSync(join(dir, "backend", "server.py"))) return dir;
    if (dirname(dir) === dir) {
      throw new Error(`no repository root above ${from}: no backend/server.py found`);
    }
  }
}

export const REPO = repoRoot(FRONTEND);

export const FIXTURE_PASSWORD = "lantern-quartz-meridian-8811";

/** Ask the kernel for a port nobody is using, then release it. */
export function freePort() {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
  });
}

function waitForLine(child, needle, label, timeoutMs = 60_000) {
  return new Promise((resolve, reject) => {
    let buffer = "";
    const timer = setTimeout(() => {
      reject(new Error(`${label} did not report ready in ${timeoutMs}ms. Saw:\n${buffer}`));
    }, timeoutMs);

    const onChunk = (chunk) => {
      buffer += chunk.toString();
      if (buffer.includes(needle)) {
        clearTimeout(timer);
        resolve(buffer);
      }
    };

    child.stdout.on("data", onChunk);
    child.stderr.on("data", onChunk);
    child.on("exit", (code) => {
      clearTimeout(timer);
      reject(new Error(`${label} exited early with ${code}. Output:\n${buffer}`));
    });
  });
}

/**
 * Kill a child and everything it spawned.
 *
 * `detached: true` puts the child in its own process group so the negative-pid kill reaches
 * the whole group. Without it, killing the launcher leaves the real server running: it holds
 * its stdio pipes open, Node's event loop never empties, and `node --test` hangs after the
 * last assertion has already passed -- which looks exactly like a failing test and is not one.
 */
function killTree(child) {
  if (child.pid === undefined || child.exitCode !== null) return;
  try {
    process.kill(-child.pid, "SIGTERM");
  } catch {
    try {
      child.kill("SIGKILL");
    } catch {
      /* already gone */
    }
  }
  child.stdout?.destroy();
  child.stderr?.destroy();
}

export async function startFixtureApi() {
  const dir = await mkdtemp(join(tmpdir(), "dispatchos-fixture-"));
  const port = await freePort();
  const child = spawn(
    "python3",
    [join(HERE, "fixture_api.py"), "--port", String(port), "--db", join(dir, "d.db")],
    { cwd: REPO, stdio: ["ignore", "pipe", "pipe"], detached: true },
  );
  await waitForLine(child, `FIXTURE READY ${port}`, "the DispatchOS fixture API");
  return {
    port,
    origin: `http://127.0.0.1:${port}`,
    async stop() {
      killTree(child);
      await rm(dir, { recursive: true, force: true });
    },
  };
}

/**
 * Wait until something answers on the port.
 *
 * Deliberately NOT a "look for the ready line" wait like the fixture uses. `next start`
 * writes its banner only to a TTY -- piped, it prints nothing at all, so waiting for text
 * hangs until the timeout with no output to explain why. Asking the port whether it is
 * serving is both the thing actually being waited for and the thing that cannot change
 * format between Next releases.
 */
async function waitForPort(origin, label, timeoutMs = 90_000) {
  const deadline = Date.now() + timeoutMs;
  let lastError = "no attempt made";
  while (Date.now() < deadline) {
    try {
      const response = await fetch(origin, { signal: AbortSignal.timeout(2_000) });
      if (response.status > 0) return;
    } catch (cause) {
      lastError = cause instanceof Error ? cause.message : String(cause);
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error(`${label} never answered on ${origin} in ${timeoutMs}ms. Last: ${lastError}`);
}

/** `next start` against the already-built .next, with /api/* pointed at the fixture. */
export async function startNextServer(apiUpstream) {
  const port = await freePort();
  const origin = `http://127.0.0.1:${port}`;
  // The local binary directly, not `npx`: npx is a launcher process, so SIGTERM to it leaves
  // the real server running and the test process alive forever.
  const child = spawn(join(FRONTEND, "node_modules", ".bin", "next"), ["start", "--port", String(port)], {
    cwd: FRONTEND,
    stdio: ["ignore", "pipe", "pipe"],
    detached: true,
    env: {
      ...process.env,
      NODE_ENV: "production",
      NEXT_TELEMETRY_DISABLED: "1",
      SYMONEURAL_API_UPSTREAM: apiUpstream,
    },
  });
  // Keep the output so a startup crash is reportable rather than silent.
  let output = "";
  child.stdout.on("data", (c) => (output += c.toString()));
  child.stderr.on("data", (c) => (output += c.toString()));
  child.on("exit", (code) => {
    output += `\n[next start exited with ${code}]`;
  });
  try {
    await waitForPort(origin, "the Next production server");
  } catch (cause) {
    killTree(child);
    throw new Error(`${cause instanceof Error ? cause.message : cause}\nOutput:\n${output}`);
  }
  return {
    port,
    origin,
    async stop() {
      killTree(child);
    },
  };
}

/** fetch that carries the DispatchOS session cookie between calls, like a browser would. */
export function makeClient(origin) {
  let cookie = "";
  return {
    get cookie() {
      return cookie;
    },
    async call(path, init = {}) {
      const headers = { ...(init.headers ?? {}) };
      if (cookie) headers["Cookie"] = cookie;
      if (init.body !== undefined) headers["Content-Type"] = "application/json";
      const response = await fetch(`${origin}${path}`, {
        ...init,
        headers,
        redirect: "manual",
        ...(init.body === undefined ? {} : { body: JSON.stringify(init.body) }),
      });
      const setCookie = response.headers.getSetCookie?.() ?? [];
      for (const raw of setCookie) {
        const pair = raw.split(";")[0];
        if (pair.startsWith("symon_dispatchos=")) {
          cookie = pair.endsWith("=") ? "" : pair;
        }
      }
      const text = await response.text();
      let json = null;
      try {
        json = text === "" ? null : JSON.parse(text);
      } catch {
        json = null;
      }
      return { status: response.status, headers: response.headers, text, json };
    },
  };
}
