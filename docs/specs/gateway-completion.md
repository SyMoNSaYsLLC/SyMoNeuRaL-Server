# Gateway completion — what stands between `offline` and a working surface

**Audit date 2026-08-17. This is a spec, not a state document.** `.claude/HANDOVER.md` remains
the one state document and `.claude/CLAUDE.md` the one rulebook — see `README.md` in this
directory.

---

## STATUS, 2026-08-17 — every agent-doable item in §7 is now done

The line "Nothing here has been implemented" was true when this was written and is not any
more. What changed, against §7's own numbering:

| Item | | State |
|---|---|---|
| 1 | fail-closed rule written at the insertion point | **done** — `chain.py` module docstring and `unit_state()` |
| 2 | `test_gateway.py` | **done** — 57 tests, all offline, incl. the "no environment produces a non-`offline` state" tripwire |
| 3 | base58check, not base58 shape | **done** — `address.py`, checksum verified |
| 4 | read-only chain reader, cached off the status path | **done** — `chain.py` + `ChainCache` (TTL 60 s) + `refresher()` |
| 5 | network → endpoint map | **done** — `chain.NODES`, no `SYMONEURAL_GATEWAY_NODE_URL` |
| 6 | frontend assertion | **done** — two, in `tests/frontend.mjs`; both verified to go red when broken |
| 8 (a) | draft the Solidity | **done** — `ops/gateway/contracts/`, compiled AND executed, 17/17 |
| 7, 8 (b), 8b, 9 | keypair, deployment, page redeploy, service env | **not done — yours.** `ops/gateway/DEPLOY.md` is the procedure |
| 10, 11 | the off-chain verifier, and gating that actually gates | **done** — `backend/apps/gateway/`, 47 tests. Every fail-closed case was verified to go red with the bug put back |
| 12 | key exchange, or an explicit decision not to do DRM | **decided** — payment rail, not DRM, per the review's own recommendation. Written into `settlement/__init__.py`, `ops/gateway/DEPLOY.md` and the page |
| 13 | `ready` | **reachable, and correctly not reached.** `unit_state` can now return it, through exactly one route: a settlement recorded against the configured network *and* contract. None has ever settled, so the rack reads `offline` |
| — | a payment path a real person can complete | **not built.** Quoting is a CLI invocation; a buyer needs a page. This is now the only engineering left before `ready` |
| 7, 8 (b), 8b, 9 | keypair, deployment, page redeploy, service env | **not done — yours** |

**§7 phase 3 said "do NOT start until the fail-open question is resolved". It is resolved, in
writing, which is what unblocked 10–13.** The gate was never that the work was hard; it was
that starting it without an answer would have baked an unexamined authorization model into the
product. The answer is the one the review recommended, it is recorded in three places, and it
is cheap to reverse — one docstring, one page paragraph, no code.

**A correction to this document's own framing.** The heading above says "every agent-doable
item is done", and §7 marks 10–13 as **(c)**, blocked. That reading put the surface's
completion behind a keypair and two `sudo` commands, and it was wrong: `unit_state`'s first
condition for `ready` is a daemon that exists, and none did. Garrett with a mainnet key and
full root still could not have made this surface honestly green. The blocker was code, and
code is the agent-doable kind.

**Two gaps this spec did not anticipate, both now closed:**

- **The transport was never exercised.** All 57 tests inject `fetch=`, so `chain.http_post`
  had never run against a real node — "it compiled" wearing the costume of "it passed".
  `python3 -m apps.gateway` now reads three live networks in both directions with four
  negative controls. Measured: mainnet head block **85,439,122** in 430 ms, USDT reads back as
  `TetherToken` with 33 ABI functions, and the same address on Nile and Shasta reads *absent*.
- **The contracts were never executed.** `ops/gateway/test_contracts.mjs` runs them in a local
  EVM at the same `istanbul` hardfork the artefacts are compiled for: replay, expiry,
  wrong-signer, tampering, signature malleability, and the unpaid-quote rollback. 17/17.

**§6 flags 1 and 3 are also fixed**, and flag 2 is defused rather than deferred: the page no
longer hardcodes deployment state at all. It said "Nothing is deployed yet" and "Nothing here
is measured", both of which a deployment turns into a live page contradicting the API. Those
facts now come from the status line, read verbatim from `/api/status`, so **the page will not
need re-editing when a contract lands.**

**The state is still `offline`, on every path, and that is the correct outcome.** §4 is
unchanged and remains the authority on what `ready` would take.

---

> **Re-grep every `file:line` below before trusting it.** `backend/server.py` and
> `tools/build/build_pages.py` were being edited by other agents *during* this audit — `GATEWAY_BODY`
> moved from 1221 to 1224 and the gateway `Unit(...)` from 1391 to 1405 while it was being
> written. Line numbers are given as a courtesy; **the symbol name is the real citation**, and
> `backend/apps/gateway/__init__.py` is the one file here that nobody else was touching.

Source of the design: `references/Projects_Crypto/TRX_POC (1).pdf` (gitignored, 1pp), reviewed
in `docs/specs/symon-ml-review.md`. Quoted by reference only, as that review does.

---

## 0. THE FAIL-OPEN QUESTION — answered first, because it was asked first

### The Gateway does **not** share the SyMoN_ML fail-open flaw, and does not share that code path.

Verified by reading, not assumed:

- **`backend/apps/gateway/__init__.py` imports `os` (line 55) and `re` (line 56). That is the
  complete import list.** No `requests`, no `httpx`, no `tronpy`, no `subprocess`, no socket.
  The module cannot reach the network, so there is no network failure for it to fail open on.
- **`_check_local_sandbox_state` does not exist anywhere in this repo.** Neither does
  `auth_daemon.py`. A repo-wide grep for
  `auth_daemon|trongrid|tronweb|TronWeb|tronpy|_check_local_sandbox_state` matches exactly three
  files: `.claude/HANDOVER.md`, `docs/specs/symon-ml-review.md`, and the word "TronWeb" inside
  the gateway module's own docstring. No code.
- **All five returns in `unit_state()` are `"offline"`** — lines 90, 93, 97, 99 and 102.
  There is no `ready` branch anywhere in the file. The function has no code path to a
  permissive answer, because it has no code path to *any* affirmative answer.
- **There is no `try`/`except` in the file.** Nothing swallows an exception into a default.
  Were one to occur it would surface as a 500 on `/api/status`, not as a granted licence.
- **Most importantly: the Gateway makes no authorization decision at all.** Its single
  consumer is `backend/server.py:1321`, which puts the returned strings into the rack `Unit(id="gateway", ...)` at
  `backend/server.py:1405`. The output is a *display string*. Nothing is gated on it, nothing is
  unlocked by it, no file is decrypted by it. There is nothing for a fail-open to open.

### The flaw is ahead of this code, not behind it. That is the real finding.

`unit_state()` lines 100–103 carry this comment:

> `# Configured, but this module does not reach the chain, so it will not claim the`
> `# contract is live. Verifying that needs the daemon, which is not built.`

**That is the exact insertion point for the bug.** The natural next commit is "reach the chain
and report what is there", and the natural shape of that code is
`try: <trongrid lookup> ... except: <fallback>` — which is Part 9's shape, one keystroke of
laziness from Part 9's outcome. The Gateway is clean today because it does nothing; it
inherits the whole hazard the moment it does something.

So the rule for every item below: **a Gateway that cannot verify must return `offline`.**
Unreachable node, non-200, rate limit, DNS failure, timeout, malformed JSON, empty result —
all of them are `offline`, and each says which one it was. No `except` in this module may ever
return anything other than `offline`.

**Bringing the Gateway "online" in the full sense means introducing an authorization decision
that does not exist today.** That is the moment the SyMoN_ML review's findings 1 and 2 stop
being about someone else's PDF and start being about our code. Items marked **(c)** below are
the ones that cross that line, and none of them should be started until finding 2 (key
exchange — a blockchain is public, the key cannot live on it) has an answer.

---

## 1. The end state, stated plainly and early

**A genuinely working *testnet* surface needs no money and no real funds.** That is the useful
answer, and it is backed by measurement in §5: Nile and Shasta both answered on this box today,
and a contract-existence check needs no wallet, no private key, no library and no signature.

**What cannot be delegated to an agent is Garrett generating a keypair and deploying a
contract.** Not because it costs money on a testnet — it does not — but for the same reason
`.claude/HANDOVER.md` §5 item 0 makes regenerating the contract signing key his call and not an
agent's: a keypair and a deployed contract are company artefacts with an owner, and an agent
minting one creates a thing nobody decided to create. Testnet or not, that is a decision, not a
task.

**Money enters at exactly one place: mainnet.** Real USDT, real TRX for Energy or Bandwidth,
and a real Energy-rental account. Nothing before that step costs anything.

**And the honest ceiling: `ready` is not available even after a successful testnet
deployment.** See §4. A contract on Nile plus a node that answers earns a much better `offline`
detail line, not a green light.

---

## 2. What is implemented versus stubbed — every function

The module is 104 lines, and **nothing in it is a stub in the placeholder sense**: there is no
`pass`, no `NotImplementedError`, no hardcoded sample value, no `TODO`. Every function does
real work. The work is just very narrow — it reads environment variables and validates their
shape. Nothing reaches the chain, and no daemon exists.

| Function | Line | Does real work? | What it actually does |
|---|---|---|---|
| `enabled()` | 70 | Yes | `os.environ["SYMONEURAL_GATEWAY_ENABLED"] == "1"`. Exact-match, so `true`/`yes`/`on` do **not** enable it. Fails closed on a typo. |
| `network()` | 74 | Yes | Reads `SYMONEURAL_GATEWAY_NETWORK`, strips, lowercases. Returns `""` when unset. |
| `contract()` | 78 | Yes | Reads `SYMONEURAL_GATEWAY_CONTRACT`, strips. No validation here. |
| `unit_state()` | 82 | Yes | The whole state machine. Four guards, five returns, all `"offline"`. |
| `ADDRESS` (regex, line 61) | 61 | Yes, partially | `^T[1-9A-HJ-NP-Za-km-z]{33}$` — base58 *alphabet and length* only. See the finding below. |
| `NETWORKS` (dict, line 63) | 63 | Yes | `shasta` / `nile` / `mainnet` → display names. |

**What does not exist at all** — these are not stubs, they are absent:

- No chain client. No RPC call, no HTTP call, no node URL constant. `NETWORKS` maps to display
  names, **not to endpoints** — there is not even a URL in the file.
- No off-chain daemon. Nothing in `backend/`, nothing in `scripts/`, nothing anywhere.
- No contract source. No `.sol` file exists in the repo.
- No wallet, no key handling, no signing. Deliberate — the docstring at lines 49–51 states that
  no private key is read by this module and none should ever be in the environment of a
  public-facing web process. That is the correct position and item 9 below preserves it.
- No API routes. The Gateway has **no** endpoints. Compare `asicminer` (three routes) and
  `tuner` (its own `APIRouter`). The Gateway's entire public surface is one entry in
  `/api/status` and one static page.
- No tests. `backend/apps/gateway/` contains `__init__.py` and `__pycache__`, nothing else —
  unlike `licensing` (21 tests) and `tuner` (57 tests).

### Minor finding: the address check validates shape, not checksum

`ADDRESS` (line 61) accepts any 34-character string starting with `T` from the base58
alphabet. TRON addresses are **base58check**: a 21-byte payload beginning `0x41` plus a 4-byte
double-SHA256 checksum. **A transposed or mistyped character produces a string that passes this
regex and is not a real address**, and the rack would then print
`Nile testnet · TAbc12…wxyz configured` for an address that cannot exist. Decoding base58check
and verifying the `0x41` prefix and the checksum is ~15 lines with no dependency and turns a
class of silent typos into an honest "malformed". This is an **(a)** item, and a small one —
it must not crowd out the headline.

---

## 3. External dependencies, and what exists on this box today

| Dependency | Needed for | On this box today? |
|---|---|---|
| **TRON wallet (address + private key)** | Receiving licence payments; signing anything | **No.** No key material found. The module reads none by design (docstring 49–51). `backend/apps/licensing/` holds only `contract-signing.pub` — a *different* key, Ed25519 for contract keys, and its private half is already lost (HANDOVER §5 item 0). Unrelated system, do not conflate. |
| **Deployed TRC-20 licensing contract** | The whole payment rail | **No.** No `.sol` source in the repo, no deployed address, `SYMONEURAL_GATEWAY_CONTRACT` unset everywhere. |
| **A TRC-20 token to denominate in** | "settles in USDT" | **No.** On mainnet USDT exists (`TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t`, verified live — see §5). On a testnet there is no real USDT; you deploy your own mock TRC-20, which is free and has no third-party dependency. |
| **Node / API endpoint (trongrid)** | Reading chain state | **Reachable, but no client code.** Measured today: Nile 200 in 1.06 s, Shasta 200 in 0.69 s, mainnet 200 in 2.64 s. |
| **Network egress** | All of the above | **Yes, verified today** — all three TRON endpoints answered from this box. |
| **A TRON Python library (`tronpy`)** | Signing; ABI encoding | **No, and probably not needed.** The system interpreter has `requests` and `httpx` only. `.claude/CLAUDE.md` forbids `pip install` into the serving interpreter. **Read-only chain queries need no library and no crypto at all** (§5) — plain HTTP JSON. Signing does need secp256k1, which is why signing belongs in the off-chain daemon with its own venv, never in the web process. |
| **Energy rental API account** | The PoC's "effectively zero fee" step | **No.** A third-party paid service requiring an account and TRX. Mainnet-only concern; on a testnet, faucet TRX covers execution directly. |
| **`SYMONEURAL_GATEWAY_*` set in the service environment** | Turning the surface on in production | **No — confirmed on the running service, not just the repo template.** `systemctl show symoneural-api -p Environment` → `PYTHONUNBUFFERED=1 SYMONEURAL_PORT=8800`; no `symoneural-api.service.d/` drop-in exists. The surface is hard-off in production. |
| **The off-chain daemon** | Approval, broadcast, unlock | **No.** Deliberately not built — `docs/specs/symon-ml-review.md` §6 records why. |

---

## 4. What `unit_state()` checks, and what would have to become true for `ready`

### What it checks, in order

1. **Line 89** — `enabled()` false → `offline`, *"designed, not deployed — see /gateway.html"*.
   **This is the branch production is on — observed, not inferred.** Both the local API and the
   public site return this unit verbatim today:

   ```
   $ curl -s https://symoneural.com/api/status   # and localhost:8800, identical
   {"id": "gateway", ..., "state": "offline", "bus": "net",
    "detail": "designed, not deployed — see /gateway.html"}
   ```

   And the *installed* unit, not just the repo template, carries no gateway switch:
   `systemctl show symoneural-api -p Environment` returns
   `Environment=PYTHONUNBUFFERED=1 SYMONEURAL_PORT=8800`, and
   `/etc/systemd/system/symoneural-api.service.d/` does not exist, so no drop-in adds one.
   (Checking the installed unit rather than the repo copy matters: HANDOVER §3.0d is a list of
   five verification steps that failed precisely because they encoded an assumption about the
   deployment instead of reading it.)
2. **Line 92** — `network()` not in `NETWORKS` → `offline`, naming what was found and what was
   expected.
3. **Line 96** — `contract()` empty → `offline`, *"<network> — no contract address set"*.
4. **Line 98** — `ADDRESS` does not match → `offline`, *"<network> — contract address is
   malformed"*.
5. **Line 102** — everything configured → **still `offline`**, *"<network> · Tabc12…wxyz
   configured — daemon not built, nothing has confirmed on-chain"*.

Every branch names the network it is pointed at. That is deliberate and correct: a gateway that
does not say which chain it is on is one misconfiguration away from taking real USDT while
everyone believes it is a test.

### What would have to become true — and it is two tiers, not one

**Tier 1 — a better `offline`. Cheap, honest, and almost entirely agent-doable.**

Replace line 102's "nothing has confirmed on-chain" with a *measured* statement: the node
answered, the chain head is at block N, and a contract does or does not exist at the configured
address. That is a real reading, it is the first genuinely measured thing this surface has ever
produced, and **the state stays `offline`** because a contract existing is not a working
licensing service.

**Tier 2 — `ready`. Not available on a testnet, and not available from a contract alone.**

On this rack, `ready` has a specific meaning set by every other unit: *this surface will do its
job if you click it.* Chat is `ready` when the weights are on disk. Tuner is `ready` because
its path actually works. For the Gateway, `ready` means a visitor can obtain a licence. So
`ready` requires **all** of:

1. A contract deployed and answering at the configured address.
2. The off-chain daemon existing, running, and reachable by whatever consumes it.
3. A payment path that a real person can complete.
4. A confirmed payment that actually **unlocks something** — which requires findings 1 and 2 of
   `symon-ml-review.md` to be resolved, because the unlock *is* the authorization decision.
5. That whole round trip exercised at least once, end to end.

**A contract on Nile with a node answering earns none of that.** It would be factually true and
still dishonest as a green light, for the same reason `.claude/CLAUDE.md` forbids decorative
indicators: the light would say "this works" when only one part of it does.

### Do NOT invent a fifth state string. This was checked, and it renders as an unearned light.

`site/console.js:47`:

```js
var pwr = u.state === 'offline' ? 'led' : 'led on';
```

**Any state that is not the literal string `offline` lights the green power LED.** Adding
`configured` or `provisioned` would light it. Worse, `site/symoneural.css:379`
(`.unit[data-state="offline"]{opacity:.55}`) would stop dimming the unit, and no
`.ustate .txt` colour rule would match, so the unit would render at full brightness with a lit
power LED and an unstyled label. The word itself survives — `console.js:32`'s `WORDS` lookup
falls back to the raw string — but the LED does not, and the LED is the thing the honesty rule
is about. This is the same shape as the bus-plate bug in HANDOVER §2c, where an unrecognised
value printed the wrong hardware.

**Carry the truth in the detail line, which is free-text and already reaches the page
verbatim** (`site/gateway.html:176` sets `d.textContent = u.detail` — "the API's own words, not
a rewrite of them").

---

## 5. Can any of this be exercised on TRON's public testnet without real funds?

### Yes. Unambiguously yes, and it is the cheapest honest path. Measured on this box, 2026-08-17.

| Endpoint | Purpose | Result today |
|---|---|---|
| `https://nile.trongrid.io` | Nile testnet full node | **200**, 1.06 s. Chain head block **70,152,715**. |
| `https://api.nileex.io` | Nile, alternate provider | **200** |
| `https://api.shasta.trongrid.io` | Shasta testnet full node | **200**, 0.69 s |
| `https://api.trongrid.io` | Mainnet (for reference) | **200**, 2.64 s |
| `https://nileex.io` | Nile faucet / join page | **200 — host reachable only.** The faucet function was *not* exercised; no TRX was requested. |
| `https://shasta.tronex.io` | Shasta faucet | **200 — host reachable only**, same caveat. |
| `https://nile.tronscan.org`, `https://shasta.tronscan.org` | Block explorers | 403 to `curl` — a bot filter, they are browser-reachable |

The node rows are genuine end-to-end measurements — a chain head came back. **The two faucet
rows are reachability only**, and this doc applies to itself the rule it applies to the page's
h1: obtaining testnet TRX is expected to be free and routine, but it has not been done here, so
it is not a measured claim. Testnet TRX is what covers Energy and Bandwidth for contract
deployment and calls; no real money is involved at any point.

### The decisive proof that the read side needs no key material

`wallet/getcontract` answers "is a contract deployed at this address" with **no wallet, no
private key, no signature, no library** — plain HTTP JSON, which `requests` (already present in
the system interpreter) can do. Run today:

```bash
# mainnet, USDT -- a contract exists, so the ABI comes back
curl -s -X POST https://api.trongrid.io/wallet/getcontract \
  -H 'Content-Type: application/json' \
  -d '{"value":"TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t","visible":true}'
# -> {"origin_address":"THPvaUhoh...","contract_address":"TR7NHq...","abi":{...}}

# the same address on Nile, where nothing is deployed
curl -s -X POST https://nile.trongrid.io/wallet/getcontract \
  -H 'Content-Type: application/json' \
  -d '{"value":"TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t","visible":true}'
# -> {}
```

**`{}` for absent, an ABI for present.** That is a clean, keyless, fail-closed-by-nature
readiness probe: absent → `offline`, unreachable → `offline`, present → a better `offline`
detail line. It is the whole of Tier 1.

### What testnet cannot prove, and must be said on the page

A test token is not USDT. Exercising the mechanism on Nile demonstrates *the mechanism* — the
contract, the confirmation, the daemon's approval pause, the unlock — and demonstrates nothing
about real stablecoin settlement, liquidity or fees. The existing code already forces the
network name into every detail string, which is exactly the right defence. Keep it.

---

## 6. `site/gateway.html` — what the page promises versus what the backend delivers

**Overall the page is unusually honest, and materially more honest than most of this audit
expected.** The claims that matter are backed, the labelling rule is followed, and the status
line is read from the API rather than hardcoded. Three flags follow, in severity order, and
none of them is a fabricated reading.

### Backed, and verified against the code

| Page claim | Verdict |
|---|---|
| "no deployed contract, no wallet, no daemon and **no key material on this box**" (`gateway.html:89–91`) | **True**, all four clauses verified in §3. |
| "~3 second confirmation" and "27 Super Representatives" labelled **vendor** (`:72–74`) | **Correct labelling** per `.claude/CLAUDE.md`. |
| "Effectively zero fee" labelled **projected**, with the reason ("Energy rental does not make execution free; it moves the cost") (`:75–78`) | **Correct, and better than the PoC**, which asserts fees are effectively zero without qualification. |
| "**Nothing here is measured**, because nothing has run" (`:79`) | **True today.** Becomes false the moment Tier 1 ships — see flag 2. |
| Pricing: "quoted, not published" → `symonsayadmin@symoneural.com` (`:81–86`) | **Compliant.** No fee figure appears anywhere on the page. |
| The steps are headed "How a licence **would** clear" (`:53`) and use conditional phrasing | **Correct.** Describes a design, not a running system. |
| The status LED (`<s></s>`, `:48`) is never given a class by the page's JS | **Honest by accident or design** — `symoneural.css:218` renders a classless `s` as an unlit grey dot. It is not a decorative green light. **Do not "fix" this by calling `status()`.** |

### Flag 1 — the h1 asserts a performance property nothing here has measured

> "Licensing that clears in seconds, and says whose number that is." (`gateway.html:39`)

The second clause is the honest one and does real work. The first states a settlement speed as
fact, in the largest type on the page, unlabelled. It is defensible — the lede immediately
below says nothing is deployed, and the callout labels ~3 s as vendor — but a reader who takes
only the headline takes away a performance claim about a surface that has never run.
**Severity: low, tension not falsehood.** Worth a look when the page is next edited; not worth
a commit on its own.

### Flag 2 — the page goes stale the instant a contract is deployed, and it is a generated file

`gateway.html:89–91` asserts "no deployed contract". **Item 8 of the plan makes that clause
false**, and this repo's recurring failure class is a live page contradicting the API. Two
things compound it:

- **`site/gateway.html` is generated**, from `GATEWAY_BODY` in `tools/build/build_pages.py` (line 1224
  at time of writing, and already moved once during this audit).
  Editing the HTML directly is thrown away on the next generator run.
- **Static files do not reach a visitor until `sudo scripts/deploy.sh --prune` runs**, which an
  agent cannot do. HANDOVER §0b is emphatic about this.

So "deploy the contract" and "update the page" are a single coupled unit of work, and the
second half needs Garrett. It is item 8b below for exactly that reason.

### Flag 3 — the page carries GPU-queueing boilerplate on a surface that never touches the GPU

`gateway.html:97–112` — "This is a 16 GB consumer card, and it is a test bench", explaining that
chat and image cannot co-reside and that you may be queued behind someone. It comes from the
shared `SHELL` in `tools/build/build_pages.py:72–73` and appears on all seven surface pages.

The Gateway is `bus="net"` (in that same `Unit(id="gateway", ...)`, `backend/server.py:1406`). It never takes the GPU lock and can never
queue behind a render. Nothing in the callout is false about the machine; it is simply not
about this surface, and on a licensing page it implies the Gateway is a GPU tenant.
`tuner.html` — also a `net` surface — at least passes `gpu=False` to `page()`, which adds a
panel that says outright that the page does not wait for the card. **The Gateway passes
neither `gpu=True` nor `gpu=False`**, so it gets the boilerplate without the clarification.
**Severity: low.** The fix touches shared `SHELL` markup used by six other pages, so it should
not be done casually or in isolation.

---

## 7. The completion plan, in order

Each item is marked:
**(a)** an agent can do it · **(b)** only Garrett (money, keys, contract deployment, sudo) ·
**(c)** must NOT be done until the fail-open question is resolved.

### Phase 0 — before anything else

**1. (a) Write the fail-closed rule down in the module, next to the insertion point.**
A comment at `__init__.py:100–103` naming `symon-ml-review.md` finding 1 and stating that no
`except` in this module may return anything but `offline`. The whole risk of this project is a
future agent adding a chain read with a permissive fallback; the cheapest defence is a warning
at the exact line where they will type it. Costs nothing, ships alone, protects everything
after it.

**2. (a) Add `backend/apps/gateway/test_gateway.py`.** There are currently zero tests on this
module while `licensing` has 21 and `tuner` has 57. Assert every branch of `unit_state()`
returns `offline`, and — the load-bearing one — assert that **no configuration of the
environment can produce a non-`offline` state**. That test is what makes a future fail-open
land as a red build instead of a silent regression. Write it before the code it guards exists.

**Write that test against behaviour, not against today's signature.** Item 4 changes
`unit_state()` from zero-argument to taking a cached reading; a test bound to the current
signature would need rewriting at exactly the commit it exists to guard, which is how a
tripwire quietly becomes a formality. Phrase it as "for every environment and every reading,
the state is `offline` until a human deletes this test".

**3. (a) Verify base58check, not just base58 shape.** §2's minor finding. ~15 lines, no
dependency, turns a class of typo into an honest "malformed".

### Phase 1 — Tier 1, the measured `offline`. No money, no keys, no contract.

**4. (a) Write a read-only chain reader, and cache it out of the status path.**
`wallet/getnowblock` and `wallet/getcontract` over plain `requests`, per §5. Three hard
constraints:

- **It must never be called inline from `unit_state()`.** `backend/server.py:1324` states the
  rule: *"`/api/status` is polled and drives the websocket, so nothing in here may block."*
  The measured latencies are 0.69–2.64 s. Inline, that is added to every status poll and every
  WebSocket frame for every visitor.
- **Follow the precedent one line above.** `backend/server.py:1320` is
  `asicminer.unit_state(_asic_cache.get())` — the ASIC surface takes its reading as an argument
  from a cache and does no I/O in the status path. `gateway.unit_state()` should gain the same
  shape: `unit_state(reading)`, with a background/TTL cache supplying it, and `None` meaning
  "not yet probed" → `offline`.
- **Every failure returns `offline` with the reason.** Timeout, non-200, unparseable body,
  `{}` from `getcontract` — each is a distinct, honest detail string. This is the item where
  the fail-open bug would be born; item 1's comment and item 2's test exist to catch it here.

**5. (a) Add a `NETWORKS` → endpoint mapping.** The dict at line 63 maps to display names only;
there is not a URL in the file. Endpoints in §5. Keep mainnet's URL present but note that the
switch defaulting away from mainnet (docstring 45–47) is a deliberate safety property.

**6. (a) Add a frontend assertion to `tests/frontend.mjs`.** Per `.claude/CLAUDE.md`, an
assertion goes in whenever a frontend bug is fixed — and there is a standing trap here: the
suite currently touches `gateway.html` only in the script-error sweep (`tests/frontend.mjs:214`).
Assert that the page's `#gwstate` shows the API's own state string and `#gwdetail` its own
detail, and — per HANDOVER §3.0's repeated lesson — **verify the assertion fails when you break
it**, or it is vacuous.

*After phase 1 the rack still reads `offline`, and that is the correct outcome.* The detail
line goes from "designed, not deployed" to a live reading of a real chain. That is the first
measured thing this surface has ever produced.

### Phase 2 — the testnet deployment. Still no real money; needs Garrett.

**7. (b) Generate a TRON keypair for the testnet operator wallet, and fund it from a faucet.**
Free, but it is a company key with an owner, and HANDOVER §5 item 0 sets the precedent that key
generation is Garrett's call and not an agent's. **Not in `/tmp` this time — that is what lost
the last one.** The private key goes on Garrett's own machine and never into
`ops/units/symoneural-api.service` or any web-process environment; the module's docstring (49–51) is
already explicit and item 9 depends on it.

**8. (b) Write and deploy the licensing contract to Nile.** A TRC-20-denominated licensing
contract plus, for the testnet, a mock TRC-20 to denominate in (free, and no third-party
dependency). An agent can draft the Solidity **(a)**; deploying it under a company key is
**(b)**. The contract address is public data and is safe in the service environment.

**8b. (b, coupled to 8) Update `GATEWAY_BODY` and redeploy the page.** Per flag 2:
`gateway.html:89–91` asserts "no deployed contract", which item 8 makes false. Edit
`GATEWAY_BODY`, `tools/build/build_pages.py:1224` **(a)**, run the generator twice and diff **(a)**, then
`sudo scripts/deploy.sh --prune` **(b)**. This is not optional cleanup — a live page
contradicting the API is this repo's most-repeated failure.

**9. (b) Set `SYMONEURAL_GATEWAY_ENABLED=1`, `SYMONEURAL_GATEWAY_NETWORK=nile`, `SYMONEURAL_GATEWAY_CONTRACT=T…`.**
Needs an edit to the `@@ROOT@@` template in `ops/units/symoneural-api.service` and a reinstall plus
`sudo systemctl restart symoneural-api`. Contract address and network name are fine there.
**A private key never is.**

### Phase 3 — do NOT start until the fail-open question is resolved

Everything below introduces the authorization decision that does not exist today. Each is
**(c)**, and the gate is `docs/specs/symon-ml-review.md` findings 1 and 2 having answers that
are written down and agreed.

**10. (c) The off-chain daemon.** Approval pause, log hashing, broadcast. It holds the private
key, so it runs on the operator's machine and gets its own venv — never the serving
interpreter, per `.claude/CLAUDE.md`.

**11. (c) Payment verification that actually gates something.** This is where finding 1 lands
in our code. The review's specifics are the checklist: verify the **amount**, the **sender**,
the **token contract**, and the **timestamp** — the PoC's version checks only recipient and
`confirmed`, so any confirmed transfer of any token of any size at any time granted a permanent
licence. And **no caching of a positive result for the process lifetime**: the review notes
`is_licensed` was set once and never re-checked or expired.

**12. (c) Key exchange, or an explicit decision not to do DRM.** Review finding 2 is unresolved
and may not be resolvable as described: a blockchain is public, so the decryption key cannot
live in the contract; if a server we run hands out the key, that server is the licence authority
and the chain is a payment rail rather than a moat. The review's own recommendation is the
honest one and should be taken seriously as the answer rather than a fallback — **keep the
at-rest encryption and the payment rail, and describe them as exactly that.** A payment rail is
a good product. A DRM claim we cannot back is the thing this site exists to argue against.

**13. (c, and only after 10–12) `ready`.** Per §4, all five conditions, ending in one
end-to-end round trip actually completed. Until then the answer is a better `offline`.

### Mainnet — where money actually enters

**14. (b) Everything above, repeated on mainnet, with real USDT and an Energy-rental account.**
Nothing before this step costs anything. `SYMONEURAL_GATEWAY_NETWORK=mainnet` should be the last thing
that ever changes, and the module's insistence on naming the network in every detail line is the
safeguard that stops a test being mistaken for production. Keep it.

---

## 8. Summary for the decision

- **The Gateway has no fail-open path.** It has no network code, no `try`/`except`, no `ready`
  branch, and it authorizes nothing. Verified by reading.
- **The hazard is entirely in front of us**, at `__init__.py:100–103`, and items 1–2 exist to
  put a tripwire there before anyone writes the code.
- **Phase 1 (items 1–6) is fully agent-doable, costs nothing, needs no key, no contract and no
  sudo, and produces the first genuinely measured reading this surface has ever had** — while
  still honestly reporting `offline`.
- **Phase 2 needs Garrett** for a keypair, a contract deployment, and two sudo commands. It
  needs no real money — Nile is free.
- **Phase 3 must not start** until the key-exchange question has an answer, and the honest
  answer may be "no DRM; the chain is a payment rail".
- **`ready` is not on the table** for a testnet deployment, and proposing it would be the
  decorative indicator `.claude/CLAUDE.md` forbids.
