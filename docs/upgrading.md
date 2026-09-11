# Upgrading a SyMoNeuRaL install

This is the document behind the instructions the packaging scripts print: the operator
lines `scripts/build-deb.sh` writes into the `.deb`'s postinst, and the apt-source setup
`scripts/build-apt-repo.sh` prints after refreshing the repository. Everything here
describes what those scripts and `bin/symoneural-cli` actually do today, on this tree.
Where a path is designed but not yet usable, it says so instead of promising.

There are three upgrade paths. All three converge on the same script — `scripts/deploy.sh`
owns publishing, and nothing else reimplements it — so the choice between them is about
who initiates and what happens around the publish, not about what lands in the webroot.

| Path | Command | For |
|---|---|---|
| direct | `sudo scripts/deploy.sh --prune` | the reference box, from the checkout |
| CLI | `symoneural-cli upgrade` | the same publish, plus the service restart and the record |
| apt | `sudo apt update && sudo apt upgrade` | any host that installed the `.deb` |

One thing to say plainly first: there is no git remote for this project, by design, so
"pull the latest and redeploy" is not a path. On the reference box the checkout is the
source of truth and upgrading means committing work and publishing it. Every other host
tracks this box through the `.deb`, and only through the `.deb`.

## Path 1 — `sudo scripts/deploy.sh --prune`

The primitive. It publishes the staged `site/` directory of the checkout it lives in to
`/var/www/symoneural`, and it is deliberately narrow:

- Only real web assets are copied (html, css, images, js, fonts, txt, xml). Whatever else
  is sitting in `site/` — captures, PDFs, `.json` build metadata — is listed as skipped,
  because the staging directory is a working directory and the webroot is not.
- The current `index.html` is backed up to `index.prev-<stamp>.html` first. That backup is
  the only file the script protects. Everything else in the webroot without a counterpart
  in `site/` is an orphan: reported on every run, deleted only under `--prune`.
- After publishing it verifies that every local asset reference in the deployed pages
  resolves on disk, and that check can fail the run — exit 1 with `FAILED: N referenced
  asset(s) are not on disk`. A failure there means the site is deployed but incomplete:
  fix the reference or ship the file, then re-run.

What it does not do:

- It does not build the site. It publishes whatever is staged, so the generator pipeline
  — the `tools/build_*.py` generators, then `tools/build_cachebust.py` strictly last —
  has to have been run first. Deploying a tree where a generator ran after the stamper
  ships pages whose stylesheets are cacheable for a week with no way to invalidate them,
  because the generators emit unstamped asset references and only the stamper rewrites
  them to `?v=<content hash>`.
- It does not restart anything. The running API keeps serving the old code until something
  restarts it; that is the CLI's and the postinst's job, below.
- It does not touch weights, engine binaries, or state.

## Path 2 — `symoneural-cli upgrade`

The operator front end to path 1 (`bin/symoneural-cli`, `cmd_upgrade`). It calls
`scripts/deploy.sh --prune` rather than reimplementing the orphan scan, the prune
semantics or the reference check, and adds exactly the things `deploy.sh` has no opinion
on:

- **Root, handled.** The webroot is root-owned, so if run unprivileged it re-execs itself
  under `sudo` instead of printing an instruction to run a different command.
- **A restart, gated.** After a successful publish it restarts `symoneural-api` only if
  `systemctl is-active` says the unit is running here. `is-active`, not `is-enabled`: a
  unit that is enabled but deliberately stopped must stay stopped, and `restart` would
  start it. On a box where the API runs manually under `scripts/symoneural.sh`, or not at
  all, nothing is restarted and it says so.
- **A record.** The verdict — `ok: <timestamp>` or `FAILED: <timestamp>` — is written to
  `/var/lib/symoneural/last-deploy` (override the directory with `SYMONEURAL_STATE_DIR`).
  Both `symoneural-cli status` and the next `upgrade` read it back, so a failed deploy is
  a line in the next status output, not a memory.

Two flags: `--check` prints what would happen and exits, without root and without
deploying; `--no-restart` publishes the site but leaves the service running the old code.
If `/etc/apt/sources.list.d/symoneural.list` exists it also points out that
`sudo apt update && sudo apt upgrade` does this too, because on such a host both paths
are live and they do the same publish.

A failed deploy leaves the service alone: restarting into a webroot the reference check
just called incomplete would trade a known-good running state for a known-bad one.

## Path 3 — apt

Two scripts stand behind this path, and both run on the build box, not the target.

**`scripts/build-deb.sh`** builds the package from the checkout: every tracked file, minus
an exclusion list that is enforced by a guard, not a comment — the build refuses to run if
the training corpus, the dataset builders, the adapter directories or
`backend/apps/remix/.env` reach the payload. The version string is
`0.1.0+git<date>.r<commit count>.g<sha>`, and the shape is load-bearing: dpkg compares
versions component-wise and a bare commit SHA is not monotonic, so the date leads, the
count breaks ties within a day, and the SHA is identification only. If the tracked tree is
dirty the build says so — that package matches no commit. The package installs to
`/opt/symoneural`, puts `symoneural-cli` on PATH, and declares its Python dependencies so
`sudo apt install ./symoneural_<version>_all.deb` (apt, not `dpkg -i`) resolves them.

**`scripts/build-apt-repo.sh`** publishes built packages into a flat local repository,
default `/home/google/symoneural-apt` (`--repo DIR` to move it, `--build` to build a fresh
package from HEAD first). It keeps every version, not just the newest — apt picks the
highest itself, and the predecessors are what make rollback a working command rather than
a sentence. Telling apt about the repository is a one-time, per-host line which the script
prints rather than runs:

    echo 'deb [trusted=yes] file:///home/google/symoneural-apt ./' \
        | sudo tee /etc/apt/sources.list.d/symoneural.list

`trusted=yes` is a real reduction in what apt verifies, and the script's header states
the honest trade: the repository is a directory on this disk, and whoever can write to it
can already write to `/opt/symoneural` directly. That reasoning stops holding the moment
the repository is served over a network — for that, pass `--sign`, which writes a signed
`InRelease` and prints the keyring install command instead. If the account has no gpg
secret key, `--sign` refuses rather than silently falling back to unsigned.

From then on, `sudo apt update && sudo apt upgrade` picks up every published build. On
upgrade the package's postinst:

- prints the CLI orientation lines (`status`, `upgrade`, `tools`, `mcp`);
- republishes the site by running `/opt/symoneural/scripts/deploy.sh --prune` — the
  packaged equivalent of path 1, publishing the `site/` that shipped in this version of
  the package — but only if `/var/www/symoneural` already exists and looks like ours
  (`index.html` and `symoneural.css` present). An empty or foreign webroot would have
  every file in it reported as an orphan and deleted, so on a host with no deployed site
  it deploys nothing and says so;
- skips the webroot entirely if `/etc/symoneural/no-auto-deploy` exists;
- records the outcome in `/var/lib/symoneural/last-deploy` either way. A failed deploy
  does not fail the package — dpkg would leave it half-configured, which is worse than a
  site that needs one more command — the failure is recorded and printed loudly instead;
- restarts `symoneural-api` only if `systemctl is-active` says it is running, same rule
  and same reason as the CLI.

What apt does not do: it does not build or publish packages. A new commit reaches
subscribed hosts only after someone runs `./scripts/build-apt-repo.sh --build`; until
then `apt upgrade` truthfully reports nothing to do. Nothing polls or self-updates —
every upgrade on every path is operator-initiated.

## Rollback

`sudo apt install symoneural=<older version>` — the repository keeps every version for
exactly this. Installing an older package reruns its postinst, which republishes that
version's staged site under the same webroot gates, so code and site roll back together.

That is the only real rollback. `deploy.sh` protects nothing across runs except the
`index.prev-<stamp>.html` backup it took on the current run, so on the direct path an
unwanted publish is undone by fixing `site/` and publishing again, not by restoring.

## What no upgrade path does

- **Weights.** Roughly 104 GiB on the reference box (recorded in the package description
  and the recipes). They are fetched separately by `scripts/fetch-models.sh` into
  `backend/models/` and no package or publish step touches them.
- **Engine binaries.** llama.cpp and stable-diffusion.cpp are built from `contrib/` on
  the target, against its own driver and compute capability. Until both exist,
  `symoneural-cli status` reports the surfaces as not built, which is accurate.
- **The trade secret.** The training corpus, the dataset builders and the adapter
  directories never ship on any path; both the `.deb` build and the Yocto stack recipe
  delete-then-verify before packaging and abort if any of them survives.
- **Service installation.** The `.deb` installs no systemd unit and starts nothing. The
  unit is installed from the checkout by `sudo scripts/install-service.sh`, which
  substitutes the repo root into the `ops/symoneural-api.service` template.
- **Configuration and state.** `/etc/symoneural/` and `/var/lib/symoneural/` are left
  alone apart from the one-line `last-deploy` verdict.

## Not supported yet, plainly

- **Upgrading over a network.** Nothing publishes the apt repository off this box today.
  The pieces exist (`--sign`, the keyring line, pointing the source at a network path),
  but no remote host is subscribed to anything and no signed repository has been stood up.
- **Yocto targets.** `yocto/meta-symoneural-core/recipes-symoneural/images/symoneural-image.bb`
  sets `package-management`, and the distro packages as `.deb`, precisely so a built
  target is capable of consuming this same repository with `apt update && apt upgrade`.
  Two halves are missing, and the recipe's own comment names the second: no such image
  has ever been built — the kernel provider gap fails the task graph — and the flat
  repository is a build-host `file://` path no target can see, so reaching one takes the
  network serving and `--sign` work from the bullet above, which no script here does yet.
  Until both land, every update of a deployed target would be a reflash.
  `yocto/README.md` has the honest state.

## Verifying an upgrade

`symoneural-cli status` prints the `last-deploy` verdict whenever one has been written,
and prints nothing on a host where nothing ever wrote it — an invented "never deployed"
row would be a reading of a file that does not exist. The deploy log from the apt path is
kept at `/var/lib/symoneural/last-deploy.log`. `dpkg-deb -I <file>.deb` inspects a built
package before it is published, and the build prints that line every time.
