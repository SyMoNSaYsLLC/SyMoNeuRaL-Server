# Restricted customer previews — staged here, deliberately not in `site/`

Pages in this directory are **customer previews awaiting a protected install**. They are kept
out of `site/` on purpose, and the reason is mechanical rather than stylistic.

## Why not `site/`

`scripts/deploy.sh` publishes `$ROOT/site` at `-maxdepth 1` into `/var/www/symoneural`, and
`ops/units/symoneural-deploy.service` is **enabled** with `--prune`, so that publish runs **at every
boot** without a person. A restricted page sitting in `site/` is therefore one reboot away from
being served — and if the matching access-control block is not yet installed in the live web
server config at that moment, it is served **with no protection at all**.

That is the whole hazard, and it is not hypothetical: the two halves of a protected page live
in two different files, only one of which deploys automatically. Staging the page here means
the automatic half cannot run ahead of the manual half.

`docs/` is invisible to the publisher (it reads only `$ROOT/site`), so nothing in this
directory can reach the webroot by accident.

## Install order — the manual half goes first

**The order is the safety property.** Reversed, there is a window in which the page is public
and unprotected.

1. **Install the web server config and reload it**, so the access-control block for the page's
   exact path is live. Verify the path answers `401` before continuing.
2. **Move the page into `site/`.**
3. **Re-run `python3 tools/build/build_cachebust.py`** — it does not reach this directory, so asset
   stamps are only refreshed once the page is in `site/`. Run it twice and diff; it must be a
   no-op the second time.
4. **Re-run the page guards.** A page under `docs/` is outside every one of them, and they all
   glob `site/*.html`:
   - `python3 tools/audit/check_links.py`
   - `cd backend && python3 -m pytest apps/test_brand_boundary.py apps/test_streamer_migration.py -q`
5. **Publish** with `scripts/deploy.sh`, and confirm the live path still asks for credentials.

## What these pages must not contain

They are customer previews, **not source documentation**. No architecture, no data model, no
interface or route listings, no build sequence, no infrastructure internals, no repository
paths, and no specific hardware configuration. A preview that contains the recipe is the
recipe.

They must also carry no credential of any kind — not the value, not a hint at its shape, and
no description of the mechanism protecting them. The lock is not documented on the door.

## Future production gate

A real EULA / terms-acceptance flow should be **server-side** and should record account
identity, timestamp, accepted terms version, IP and user-agent if legally approved, and
accepted scope. The current preview page only includes a **front-end acknowledgment panel**
and does not represent a production legal signature system.

Concretely, what the panel on the page is not: it is not a signature, it does not identify the
viewer, it records nothing outside that browser's session storage, and it can be stepped past
by anyone willing to edit one class in the page. It is review discipline — it makes the
boundaries impossible to miss before the content is read — and it should never be described,
in copy or in conversation, as acceptance having been captured.

## Customer confidentiality posture

Treat customer ideas, workflows, routes, pricing logic, policies and operational details as
**confidential scoping material**. In practice:

- Do not publish customer-specific details outside protected preview paths.
- Do not paste customer-sensitive details into public docs.
- Do not put customer-sensitive details in commit messages — `git log` is permanent here and
  is read far more often than the file it describes.
- Do not create customer exports without sanitisation.
- Offer a mutual NDA before deeper production discovery, if asked or if sensitive material
  will be exchanged.
- Formal confidentiality obligations get reviewed in written terms, not asserted on a page.

**Say what is true and no more.** The page states that SyMoNeuRaL *voluntarily treats* this
material as confidential and that a mutual NDA *can be signed* — both are accurate. It does not
say an NDA is in force, that confidentiality is guaranteed, or that anything on the page is
legally binding, because none of that would be true without a signature. A customer who later
discovers the protection was weaker than the wording implied has been misled, and that costs
more than the reassurance was worth.

None of this is legal advice, and nothing here has been through a lawyer.

## Scope-boundary posture

Every customer preview must define the boundary between **customer-provided inputs** and
**SyMoNeuRaL-managed implementation**, and must define it on the page rather than leaving it
to be inferred.

- The customer owns and controls business facts, approvals and production decisions.
- SyMoNeuRaL manages preview staging, runtime approach, implementation details, source,
  prompts, model files, credentials and deployment method — unless written terms say otherwise.

Three things that are easy to slide into and are each wrong:

- **Preview access is not source handoff.**
- **Preview approval is not production clearance.**
- **Customer feedback is not a signed production agreement.**

Production requires written scope and terms.

This is scope-boundary / trust-boundary discipline: name the boundaries, name who holds each
side, and name the handoff point where control transfers — so that neither side has to guess,
and so an enthusiastic conversation cannot quietly move a boundary nobody wrote down. Keep
that framing **internal**. The customer page states the boundaries plainly and in business
language; it does not explain the discipline behind them, and it must never read like a
security document.

## Customer variable boundary

This preview binds generic SyMoNeuRaL / Solo Operator / SyMon AI capabilities to **one
customer-scoped transport use case**. Customer-visible scope variables should define:
customer/business, product family, AI layer, booking workflow, messaging, records, hosting
path, production path, commercial terms, and access limits.

Do not expose raw schema, prompts, model internals, source rights, or implementation details.

The reason the boundary is stated on the page rather than assumed: a preview drawn from a
larger platform reads, to the person holding the link, as a sample of the whole platform. The
scope table is what stops "here is what we could build for your operation" being received as
"here is what you are being given."

## Mail identities — which address may appear where

Full policy: `docs/ops/SYMONEURAL-EMAIL-IDENTITY-POLICY.md`. The operator summary:

| Address | Use | On a preview page? |
|---|---|---|
| `saysupport@symoneural.com` | DispatchOS preview contact, all customer questions | **Yes — the only one** |
| `saynoreply@symoneural.com` | App/system sender later, once mail is built | No |
| `sayalert@symoneural.com` | Internal alerts later | No — never |
| `symonsayadmin@symoneural.com` | Admin / owner identity | No, without explicit approval |
| Personal Gmail | Recovery only | No — never product-facing |

The personal Gmail is a recovery identity and is **not product-facing**. It is never a system
sender, never an alert destination, and never appears on a page. "No other route was
configured" is not a reason to fall back to it — the correct behaviour with no route is to
fail loudly.

## DispatchOS production chat requirement

Customer chat transcripts and summaries should be **capable of** routing to
`symonsayadmin@symoneural.com` and saving into the customer or project folder / customer
record area. The preview page describes that destination by role — "SyMoNeuRaL admin review" —
and deliberately does not print the address: the customer needs to know a record trail exists,
not which internal mailbox receives it.

**Do not enable live mail or persistence** until provider credentials, retention rules and
customer terms are approved. Nothing in this requirement is implemented, and the preview page
says so on its face — it describes planned production behaviour, not a working path. Do not
let that wording drift into the present tense until there is a test that proves delivery and
a test that proves persistence.

No credentials, mail-provider records, DNS entries or storage paths belong in this file or in
the page. The mailbox address above is the only mail detail either one carries, and it is
there because it is the published admin address.

## Who has access to `share-dispatchos.html`

Three accounts, listed here and **nowhere on the page itself** — a customer preview must not
name internal reviewers or carry admin language.

| Account | Role |
|---|---|
| `donnie` | Customer-level preview account |
| `garrett` | Internal owner / elevated reviewer |
| `ben` | Internal elevated reviewer |
| `dispatchos-preview-test` | Shared customer-level preview testing account |

`dispatchos-preview-test` exists so Garrett and Ben can verify the customer-level view without
signing in under their own names. Its password is distributed **out of band only** and no
plaintext credential exists in this repository.

**"Elevated" is an organisational label, not a capability.** The access mechanism
authenticates; it does not authorise. All three accounts reach exactly the same page and see
exactly the same content — there is no role, tier, or internal-only view behind any of them.
Separate accounts exist so that a login can be attributed to a person and revoked on its own,
which is the only thing this buys.

If something genuinely must be internal-only, it needs its own page at its own protected path.
Do not reach for a role on the existing one, because there isn't one to reach for.

Only hashes are stored, in `ops/Caddyfile`. No plaintext lives in this repository, and nothing
anywhere records how a credential was constructed — a note about the shape of a secret narrows
the space an attacker has to search, which is exactly what committing a hash instead of a
password is meant to avoid. To rotate one, re-run Caddy's own `hash-password` and replace that
account's line; the previous hash dies the moment it is overwritten.
