# SyMoNeuRaL email identity policy — which mailbox speaks, and when

**Written 2026-08-23.** This file owns one question: **which address a model, agent, app or
page is allowed to use, and for what.** It does not configure mail, and nothing in it turns
mail on.

> **Nothing here is wired.** There is no mail sender on this box, and that is measured rather
> than assumed — `backend/apps/accounts/__init__.py:457` states it in the code that would have
> been the first consumer: *"there is no mail sender on this box to prove it any other way
> (verified: no sendmail, no MTA unit, no mail client)"*. Every mailbox below is an
> **identity policy for when sending is built**, not a description of a working path. Do not
> write copy anywhere that says mail is sending until a test proves a delivery.

## The five identities

| Mailbox | Role | Customer-facing | Used by models/agents for | Do not use for |
|---|---|---|---|---|
| `symonsayadmin@symoneural.com` | Internal admin / owner | **No** (by default) | Admin and control-plane notices; vendor and admin registration identity; owner-level and recovery notices | Automated customer mail; a public support address; any product or preview page without explicit approval |
| `saynoreply@symoneural.com` | Automated outbound sender | **Yes, as From** — once sending is implemented and approved | `From` on confirmations, receipts, password resets, system notices, booking confirmations, preview-access notices | Anything expecting a reply; human support; any inbound flow |
| `sayalert@symoneural.com` | Internal alert sink | **No, never** | Destination for server, deploy and auth alerts; failed jobs; model/runtime errors; worker failures; monitoring; billing alerts later | Anything customer-facing; marketing; support; any product or preview page |
| `saysupport@symoneural.com` | Public support | **Yes** | Contact and CTA copy; preview questions; production-scope requests; onboarding; DispatchOS / Solo Operator contact; `Reply-To` on automated mail | Automated sending identity; internal alerts |
| `garrettmcdonald87@gmail.com` | Personal recovery | **No, never** | Nothing. Recovery and backup identity only | System sending; alerts; any page; any model or agent workflow; any business output |

**The single default:** `saysupport@symoneural.com` is the **only** address that may appear on
a customer-facing surface without a specific decision. If a page needs a contact address and
nobody has said otherwise, it is that one.

## Model / agent routing policy

How a SyMon model, agent or app picks an identity. Read top to bottom; the first matching row
wins.

| Situation | From | Reply-To | To |
|---|---|---|---|
| Customer support reply, or a preview CTA | `saysupport` | — | the customer |
| Automated booking confirmation, reminder, receipt, password reset | `saynoreply` | `saysupport` *(when replies should be handled)* | the customer |
| Internal model, runtime, deploy or auth alert | *(system)* | — | `sayalert` — optionally copy `symonsayadmin` for owner-level events later |
| Admin or control-plane notice | `symonsayadmin` | — | the admin |
| Personal recovery only | — | — | `garrettmcdonald87@gmail.com` |

Two rules that are not negotiable and are easy to get wrong:

- **A model must never choose the personal Gmail for business output.** It is a recovery
  identity. It is not a fallback, and "no other route was configured" is not a reason to reach
  for it — the correct behaviour when no route exists is to fail loudly, not to send from a
  personal address.
- **Internal alert and admin mailboxes are never exposed to customers.** Not in page copy, not
  in a `Reply-To`, not in an error message, not in a bounce. `sayalert` in particular is a
  sink: it receives, it never appears.

## Future `.env` mapping

Placeholders only, and the secret values stay blank. See `docs/ops/example-env.md`.

```
SYMONEURAL_ADMIN_EMAIL      symonsayadmin@symoneural.com
SYMONEURAL_NOREPLY_EMAIL    saynoreply@symoneural.com
SYMONEURAL_ALERT_EMAIL      sayalert@symoneural.com
SYMONEURAL_SUPPORT_EMAIL    saysupport@symoneural.com
SYMONEURAL_RECOVERY_EMAIL   garrettmcdonald87@gmail.com
```

No app password, provider token, OAuth client secret or generated credential belongs in this
repository. `.gitignore:161` ignores `.env`; the tracked file is the example, and the example
carries empty values by construction.

## DispatchOS preview usage

`docs/specs/share-previews/share-dispatchos.html` shows **`saysupport@symoneural.com` and nothing
else.** No admin address, no noreply, no alert sink, no personal Gmail.

The preview's *Conversation record trail* section describes routing a conversation copy to
**SyMoNeuRaL admin review**. It names the destination by role and deliberately not by address:
the customer needs to know a record trail exists, and does not need the internal mailbox that
receives it. That routing target is `symonsayadmin@symoneural.com`, recorded here and in
`docs/specs/share-previews/README.md`.

Also: describe mail infrastructure only as *"hosted business mail infrastructure"* if it must
be described at all. Provider names, DNS records, MX hosts, SPF/DKIM/DMARC entries and
nameservers do not go on a customer page. **And never inherit a provider's certifications** —
a hosting provider holding a compliance certification is a fact about the provider, not about
SyMoNeuRaL, and repeating it as ours would be a false claim.

## Known inconsistency, recorded rather than silently fixed

**The public site currently uses `symonsayadmin@symoneural.com` as its contact address**, in
roughly 120 places across about twenty pages in `site/` plus `docs/ENGINEERING.md`. Under this
policy that address is not customer-facing and is explicitly not a public support address, so
the live site and this file disagree.

That was left alone deliberately. Most of those pages are generator-written, so the change
belongs in `tools/build/build_pages.py` and its siblings rather than in the HTML, and swapping the
public contact address on the whole site is a decision with its own blast radius — it is not a
side effect of writing down a policy. Recorded here so the next person finds the gap on
purpose instead of discovering it as a surprise.
