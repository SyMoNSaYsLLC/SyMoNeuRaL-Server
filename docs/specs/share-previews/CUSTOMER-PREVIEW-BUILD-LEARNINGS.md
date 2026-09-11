# Building a protected customer preview — what the first one taught

**Written 2026-08-23, from the DispatchOS preview.** Every step below is here because it was
either measured or went wrong once. Tags `pre-dispatchos-preview` through
`dispatchos-preview-live-protected` mark the states this describes.

## The order, and why it is the order

**Stage outside `site/` first. Install and verify auth. Only then publish.**

That sequence is not caution for its own sake — it exists because the two halves of a
protected page live in two different files and **only one of them deploys by itself**.

`scripts/deploy.sh` publishes `$ROOT/site` at `-maxdepth 1`, and
`ops/symoneural-deploy.service` is **enabled** with `--prune`, so that publish runs at every
boot with no person involved. A restricted page sitting in `site/` is therefore one reboot
away from being served — and if the access-control block is not yet in the live web server
config at that moment, **it is served with no protection at all**.

So the automatic half must never be able to run ahead of the manual half.

`docs/` is invisible to the publisher (it reads only `$ROOT/site`), which makes it a safe
staging location by construction rather than by discipline. Verified:
`grep -n 'SRC=' scripts/deploy.sh` → `SRC="$ROOT/site"`.

### The sequence

1. **Stage** the page under `docs/specs/share-previews/`. Not `site/`.
2. **Install** the config and reload. Verify the path answers **401** *before the page exists*.
   A 401 on a path with no file behind it is exactly what you want to see: it proves auth runs
   in front of the lookup.
3. **Copy** the page into `site/`.
4. **Cachebust** — see `CUSTOMER-LANDING-CACHE-PROCESS.md`.
5. **Deploy.**
6. **Prove** it: `cmp` site against webroot, then the four status checks below.
7. **Archive** only after live proof.
8. **Tag** after archive validation.

Reversed at any point, there is a window where the page is public and unprotected.

## Proving the lock, not just the door

**A 200 with the right password proves the door opens. It does not prove the lock does
anything.** Four checks, not one:

| Check | Required |
|---|---|
| no credentials | **401** |
| valid issued credentials | **200** |
| correct user, wrong password | **401** |
| unknown user, any password | **401** |

Measure these **at the commit you are recording**, not once and then transcribed forward. On
this build, `site_webroot_match` was `no` when first checked and `yes` twenty minutes later
because a deploy happened in between — writing the earlier value into a manifest would have
put a false fact into a permanent artefact.

## Web-server specifics that cost time

**Directive spelling is version-bound and fails at load, not at request.** This box runs Caddy
**2.6.2**, where the directive is `basicauth`. The underscored `basic_auth` is 2.8+ and is an
*unrecognized directive* here — the config fails to adapt, so a reload takes **the whole site
down**, not just the protected page. Measured both ways with `caddy validate` before
installing anything. Never assume a directive spelling from documentation that is not pinned
to the installed version.

**`handle` blocks are mutually exclusive.** A path claimed by an auth block no longer reaches
the catch-all `handle { file_server }`, so `file_server` has to be repeated *inside* the auth
block or the page 401s and then 404s — which looks like working auth right up until someone
logs in.

**Prove the blast radius from the adapted config, not from the diff.** `caddy adapt` before and
after the change, then compare: exactly one route gained an `authentication` handler, and all
**13** `reverse_proxy` handlers were byte-identical. That is what says `/api`, `/v1`, `/docs`,
`/studio`, `/exp` and `/livestack/*` are untouched. A Caddyfile diff looks reassuring and
proves nothing about routing.

**`ExecMainStartTimestamp` does not change on reload.** `systemctl reload` signals the running
process to re-read config; it does not restart it. The proof a reload took effect is the
behaviour changing — auth block count `0 → 2`, URL `404 → 401` — not the timestamp. Do not
read the unchanged timestamp as "the reload didn't happen".

**`basicauth` authenticates; it does not authorise.** Four accounts on this page all reach
exactly the same content. Separate names buy per-person attribution and revocation, nothing
more. "Elevated reviewer" is an organisational label, not a capability. If something genuinely
must be internal-only, it needs **its own path and its own block** — there is no role to reach
for on the existing one.

## Archives and deliverables are different things

**Keep customer deliverables separate from internal archives, and say so in the manifest.** The
archives here contain `ops/Caddyfile`, which carries password hashes. They are marked
`customer_deliverable=no` / `do_not_send_to_customer=yes` for that reason. An archive that
would be embarrassing to send is fine — an archive that is *ambiguous* about whether it can be
sent is not.

**Archive scoped, never whole-repo.** `docs/ops/EXPORTS.md` rule 1 forbids whole-repo exports
outright, and it exists because it already happened: a review zip carried
`training/corpus.jsonl` and `training/build_dataset.py`. Both are still **tracked**, so
`git archive HEAD` with no pathspec *would* include them today. `git archive` correctly
excludes everything untracked — and does nothing at all about tracked-and-protected material,
which is the category that actually leaks.

So: a scoped pathspec, plus a guard that **aborts rather than warns** before anything is
written.

**Watch for self-matching greps.** The check
`tar -tzf … | grep -E 'dispatchos-preview-test|…'` matched every line of one archive — because
the archive's own prefix directory was `dispatchos-preview-tested-<sha>/`, which contains that
string. Strip the prefix (`sed 's#^[^/]*/##'`) before scanning, or the safety check reports a
catastrophe that is really a naming coincidence, and the next real hit gets waved through.

**Check contents, not just filenames.** A secret pasted *inside* a committed file does not show
up in a path listing. Extract the archive and grep the contents for the actual credential
value.

**Tags outlast archives.** Tags cost nothing, cannot go stale, and reconstruct the state from
git itself. Tarballs are convenience copies. Tag after archive validation, so the tag is only
ever applied to a state that was actually verified.

## Credentials

- **Generate strong, store the hash, never the plaintext.** Only bcrypt hashes are committed.
  Nothing in the repository records a credential value.
- **Never describe the shape of a secret.** A note saying "28 random alphanumeric characters"
  narrows the search space, which is precisely what committing a hash instead of a password is
  meant to avoid. That sentence was written into `ops/Caddyfile` and then removed.
- **Keep the plaintext out of `$HOME` root.** It now lives in
  `~/.local/share/symoneural-secrets/`, directory **700**, file **600**, outside the repository
  so `git archive` and `deploy.sh` cannot reach it by construction.
- **`chmod` fixes future exposure only.** Two unrelated credential files on this box were found
  world-readable (`644`) and tightened to `600`. That stops it happening again; it cannot
  retract what was already readable. **If prior exposure matters, rotate at the provider** — the
  same principle as an archive: restricting a secret afterwards does not un-share it.

## Two build defects worth expecting on the next one

**Class-name collisions with the site stylesheet.** Six page-local classes — `.cta`, `.stage`,
`.steps`, `.panel`, `.msg`, `.assist` — collided with rules in the 181 KB `site/symoneural.css`,
so the page silently inherited the site's nav-button styling and rendered wrong. Namespace
every page-local class (`dx-` here) rather than hoping a name is free. `grep -cE "^\.<name>[
,{:]" site/symoneural.css` before choosing one.

**Test at mobile width, and measure rather than eyeball.** A three-column table with `nowrap`
status chips measured **519px against a 390px viewport** and scrolled the whole page sideways.
Fixed by stacking rows — not by shrinking or truncating, because the standing rule is that
layout changes must not drop data.

**Keep the test harness in step with the page.** The render script began failing with
`#t4 not visible` after the acknowledgment gate was added — the gate hides the body until
dismissed, so the harness was correct to fail and stale in not knowing about it. A harness that
fails for a *correct* reason is still a broken harness; update it in the same change.
