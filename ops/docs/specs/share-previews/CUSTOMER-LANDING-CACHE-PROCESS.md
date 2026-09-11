# Cache-busting a customer landing or preview page

**Written 2026-08-23, from the DispatchOS preview.** How to stamp a new page's asset links,
and how to prove the stamping did what you think it did.

## Why an unstamped link is a real problem

`ops/Caddyfile` sets `Cache-Control: public, max-age=604800` on `*.css`, `*.js`, `*.png`,
`*.svg` and `*.woff2`. That is correct for assets that never change and wrong for a site under
active development, and the gap between those two is a **week**.

An unstamped `href="/symoneural.css"` means a visitor's browser may hold a seven-day-old
stylesheet against markup that expects the current one. There is no way for the visitor to
know, and nothing you can do from the server to invalidate it.

This is not hypothetical. `tools/build/build_cachebust.py`'s own docstring records the shipped
failure: new HTML went out with a band the cached stylesheet had no rules for, and nineteen
full-size renders stacked down the left of the page in front of a visitor.

`?v=<hash-of-the-file>` fixes it by making the URL change whenever the file does. The long
cache stays — the asset really is immutable *for that hash*.

## When to run it

**After anything lands in `site/`, and last.**

```bash
python3 tools/build/build_cachebust.py
```

It globs `site/*.html` and `site/*/*.html`. Two consequences worth knowing:

- **A page staged under `docs/` is not stamped.** That is why a preview held outside `site/`
  has unstamped links, and why cachebust has to run *after* the copy into `site/`, not before.
- **Two levels deep is not covered.** `site/a/b.html` is stamped; `site/a/b/c.html` is not.

It is idempotent — an existing `?v=` is stripped before the current hash is applied — so
running it twice is a no-op and running it on an already-stamped tree is safe.

## Proving it changed only what you intended

A generator that touches 26 files when you expected 1 is a problem you want to find now, not
in the diff review. Take a baseline first:

```bash
md5sum site/*.html > /tmp/before.md5
python3 tools/build/build_cachebust.py
md5sum -c /tmp/before.md5 2>/dev/null | grep -v ": OK"
```

Every unchanged file reports `OK` and is filtered out; what remains is exactly the changed set.
On the DispatchOS run that was one line — `site/share-dispatchos.html: FAILED` — with the other
25 pages untouched. If anything broader appears, stop and read it before deploying.

## Proving idempotence

The standing repo rule is that generators run twice with no diff, because a generator that does
not recognise something it emits will accumulate it, one copy per run. That has happened three
times in this repository.

```bash
cp site/<page>.html /tmp/run1.html
python3 tools/build/build_cachebust.py
cmp -s /tmp/run1.html site/<page>.html && echo idempotent || echo NOT IDEMPOTENT
```

## Proving no unstamped local reference remains

Stamping "most" links is the same failure as stamping none, because the one that got missed is
the one that goes stale. Check both directions:

```bash
# what got stamped
grep -oE '(href|src)="/[A-Za-z0-9._-]+\?v=[0-9a-f]+"' site/<page>.html | sort -u

# what did NOT — must be empty
grep -oE '(href|src)="/[A-Za-z0-9._-]+\.(css|js|png|svg|woff2)"' site/<page>.html
```

The second command returning nothing is the assertion. On the DispatchOS page that was six
stamped references and zero unstamped.

`mailto:` links, in-page fragments and any absolute external URL are correctly not stamped and
will not appear in either list.

## Detecting a stale webroot

Cachebust edits `site/`. **It does not touch `/var/www/symoneural`** — only `deploy.sh` does.
So immediately after a cachebust the served page is one revision behind the source, and nothing
about the page looks wrong when you load it.

```bash
cmp -s site/<page>.html /var/www/symoneural/<page>.html && echo "in sync" || echo "webroot is stale"
```

That check caught it on this build: the page served correctly and returned the right content,
while the webroot copy still carried unstamped links.

## When to redeploy

**Redeploy if — and only if — cachebust changed a file that is already published.** If the page
has never been deployed, the next deploy picks up the stamped version and no extra step is
needed.

```bash
sudo ./scripts/deploy.sh          # no --prune the first time; read the orphan list
```

Run it **without** `--prune` first so the orphan list is printed and nothing is deleted while
you are reading it.

A redeploy of a static file needs **no Caddy reload**. Caddy serves the webroot from disk and
picks up changes immediately; reloading is for config changes only.

## Verifying parity after deploy

```bash
cmp -s site/<page>.html /var/www/symoneural/<page>.html && echo yes || echo no
```

For a protected page, re-check the access statuses too — a deploy replaces the file, so confirm
the auth in front of it is still doing its job:

| Check | Required |
|---|---|
| no credentials | 401 |
| valid credentials | 200 |
| wrong password | 401 |
| unknown user | 401 |

## Order, in one block

```
copy page into site/  ->  build_cachebust.py  ->  verify only intended files changed
                      ->  run again, verify no diff
                      ->  verify zero unstamped local refs
                      ->  deploy  ->  cmp site vs webroot  ->  re-check access statuses
```

Cachebust is always **last** before the deploy. `ops/units/symoneural-deploy.service` says why it is
deliberately not a `.path` unit watching `site/`: the generators rewrite pages in place and
cachebust stamps them afterwards, so a watcher would fire mid-sequence and publish a tree whose
stylesheet references had been stripped and not yet re-stamped — pages cacheable for a week
with no way to invalidate them, which is the exact failure this whole document exists to
prevent.
