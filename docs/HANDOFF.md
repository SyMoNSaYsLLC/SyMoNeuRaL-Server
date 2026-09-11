# HANDOFF — symoneural.com

**Canonical handoff document.** Migrated from `docs/HANDOFF.md` on 2026-09-08. The
rules that cite it now point here; the provider-specific path is retired and untracked.
Current verified state lives in `ProjectStatus.md`; this file records what will bite the
next person.

**Next executor: any coding agent or person.** The provider-specific "next executor: Claude"
language below is historical and is superseded by this line.


## Current handoff — 2026-09-09, storage reorganisation IN FLIGHT

**Next executor: any coding agent or person.** Read this before touching storage, `/yocto`,
`/mnt/gdrive` or `archive/`. The 2026-09-08 entry below is still accurate about services and
restore; this entry supersedes it only on storage.

**There is a live, unattended migration running.** It moves roughly 295 GB to Google Drive
against a measured ~5 MB/s ceiling, so it takes hours, and it is designed to survive your
session ending.

```bash
python3 tools/data/storage_reorg.py status          # the ledger
python3 tools/data/storage_reorg_supervisor.py --status
python3 tools/data/storage_final_report.py          # every gate, measured, ~10 min
tail -f .private/storage-reorg/latest.log
```

### What will bite you

1. **EXACTLY ONE storage mutation owner may exist.** `tools/data/storage_reorg.py` is it, and
   `tools/data/storage_reorg_supervisor.py` keeps one alive across restarts (it starts no
   transfers itself). Before any storage action, check `--status`. **Do not start a second
   owner and do not kill the running one** — an upload interrupted mid-flight costs the
   whole transfer again unless the remote already happens to hold it.

2. **The three old shell pipelines now refuse to run** (`exit 90` unless
   `I_UNDERSTAND_THIS_IS_RETIRED=YES`). That is deliberate: running one creates a second
   owner. Their banners record why the architecture was replaced — orphaned rclone
   children, twice, and one edit-while-bash-was-reading-it.

3. **A running Python process does not see edits to its own operation table.** Operations
   added to `storage_reorg.py` while a run is in flight take effect only on the next
   resume. This already cost something real: the owner that uploaded `/yocto/artifacts`
   started at 05:50:13, before the content-manifest code existed, so it wrote size-only
   manifests. The SHA256 data for all 105,851 files was captured locally *before* the
   sources retired (`.private/storage-reorg/contents/`) and `publish-artifact-manifests`
   publishes it. If you add operations, expect a one-cycle delay.

4. **`/yocto` is itself a git repository** — 11 commits, 254 tracked files, no remote. It
   was an unprotected sole copy of first-party build authority (121 `controlboard` files,
   15 `metrics` readouts, `matrix-run`'s two live scripts). A verified bundle now exists at
   `.private/storage-reorg/yocto-git/yocto-all.bundle` (HEAD `f43caf9f371b`). Its nine
   dirty entries are all untracked directories; the state is recorded beside the bundle.

5. **`/yocto/Archives/sendtodrive.zip` (36.9 GB) must not be deleted yet.** It is the
   recovery source for content manifests of 21 already-uploaded collections, and it holds
   the only *complete* AppleSDK — 38,310 files more than the disk copy had. Retire it only
   when `ZIP_UNIQUE_UNMAPPED_BYTES=0` is actually measured.

6. **`backend/vendor` is NOT dead reference source, despite measuring as reference-only.**
   `backend/apps/test_vendor_sdks.py` (9 tests) is a licence-compliance control that reads
   licence text out of the vendored copy *on disk* and compares it to `PROVENANCE.md`.
   Deleting the tree reclaims 131M and destroys the on-disk half of that control. It is
   preserved to Drive and kept locally; see `docs/specs/reference/VENDOR-CLASSIFICATION.md`.

7. **Two credential-bearing files were found at mode 0664** — `providerapikeys.txt` and
   `credential_setup.py`. Both now sit at 0600 under `.private/secrets/`. **Rotation is
   still outstanding and only the owner can do it**; see
   `.private/secrets/ROTATION-REQUIRED.md`. Two in different trees is a pattern: the umask
   here produces group/world-readable files unless something explicitly chmods them.

8. **`external/`'s four Claude entries (~5.5 GiB) are held on purpose** and
   `EXTERNAL_LOCAL_REFERENCE_BYTES` will not reach 0 while they remain. That is the correct
   reported outcome, not unfinished work — the hard-stop rule and section 9.6 both keep
   them until the post-exit finalizer no longer needs them.

9. **Drive permits two folders with the same name at one path.** A rename reported COMPLETE
   with 8 objects verified while a twin of that name still held 7 more at the root. If a
   collection looks half-moved, look for a twin before concluding failure.

10. **A repo-wide `grep` cannot see `review/`, and returns a clean result instead of an
    error.** Some environments wrap `grep` in a gitignore-respecting matcher, and
    `/review/` is gitignored (`.gitignore:173`). So `grep -rn '<pattern>' .` from the repo
    root silently skips every review and evidence artefact — including all of
    `review/commissioning-20260909/` — and reports no matches. Found 2026-09-09 while
    verifying a correction: the whole-tree search said clean and the file itself had five
    hits. Name the directory (`grep -rn '<pat>' review/`) or bypass the wrapper
    (`command grep -rn '<pat>' .`). **Any audit of the form "were the claims in the
    reports corrected" gets a free pass otherwise**, which is the worst kind of check.

11. **`cd backend && pytest apps -q` runs an eleven-minute, 48 GB whole-disk scan, and
    rewrites nine tracked files.** `apps/test_restore_manifests.py:158` shells out to
    `tools/build/build_restore_manifests.py` — twice, because `_generate()` is called for both the
    determinism check and the HEAD comparison. That is correct behaviour for that test and a
    trap for anyone who just wants a suite number: the run does not print for ten minutes, it
    looks hung (the process sits in `do_sys_poll`, which is the scan, not a deadlock), and it
    leaves `restore/RELEASE.json`, seven `restore/manifests/*.tsv` and
    `THIRD-PARTY-REBUILD-MANIFEST.tsv` modified in the working tree — mostly revision-stamp
    churn, since a generated manifest records the revision it was generated from.

    Hit on 2026-09-10 by an agent who had been told explicitly not to run that script and ran
    the whole directory without checking what was in it. The changes were reverted with
    `git checkout -- restore/ THIRD-PARTY-REBUILD-MANIFEST.tsv`; nothing was lost, because the
    script only reads.

    **The scoped run this branch's reports have all used, and which finishes in about 60 s:**

    ```bash
    cd backend && python3 -m pytest apps/studio apps/test_surface_split.py \
        apps/test_runtimes_registry.py apps/test_governor_paths.py -q
    ```

    If you do want the manifests regenerated, run `tools/build/build_restore_manifests.py` on
    purpose and commit the result, rather than discovering it in `git status` afterwards. Note
    that it is currently *due*: the manifests record nvcc 13.3 and driver 610.57.04, and the
    box was upgraded to 13.4 / 615.71.09 on 2026-09-09 — see `docs/ops/RUNTIMES.md`.

12. **The origin certificate renews around 2026-10-16 and that renewal needs the box to be
    reachable from the internet.** Measured 2026-09-10: the origin cert is Let's Encrypt
    `CN=symoneural.com`, valid `Aug 17 → Nov 15 2026`. Caddy's TLS automation block is empty,
    so it uses the default — ACME with `http-01` (port 80) and `tls-alpn-01` (port 443), both
    of which require Let's Encrypt to reach *this machine*.

    On the same day, `https://symoneural.com/` returned **522** from Cloudflare while the
    origin served **200** on the LAN with a valid certificate. The Cloudflare/WAN side is the
    owner's and is explicitly out of scope for agents; what is recorded here is only the
    consequence: **if that path is still dark in mid-October, renewal fails quietly and the
    certificate expires on 15 November.** Caddy has logged nothing about ACME in 30 days, so
    this box will not warn anyone.

    **It is not a cliff and it is removable.** Recovery after expiry is minutes once
    connectivity returns. Two options retire the dependency permanently rather than racing it:
    **DNS-01** via Caddy's Cloudflare plugin, which proves control with a TXT record and needs
    no inbound reachability at all; or **`cloudflared` plus a Cloudflare Origin CA
    certificate** (15-year validity, issued from the dashboard, no ACME), which also retires
    the port forward and the WAN-address question. Either turns "fix the router before
    mid-October" into "fix the router whenever."

    **Do not report a 308 from `/.well-known/acme-challenge/<anything>` as a finding.** It is
    the expected answer: Caddy installs the challenge handler dynamically during a renewal,
    ahead of its own redirects, and `tls-alpn-01` never touches port 80. A probe of that path
    returns what you expected without testing what you meant — the vacuous-guard class this
    repository keeps catching.

13. **`backend` is not a Python package, and it costs 104 `sys.path` mutations.** There is no
    `backend/__init__.py` and no `backend/apps/__init__.py`; 18 of 21 app directories have one
    (`remix` and `ravencalc` do not). Measured 2026-09-10 across tracked first-party code:
    **12 `sys.path.insert` calls in 10 production files, 63 in 52 tests, 29 in 27 tools.**

    The live consequence is not the ugliness. With `apps/` on `sys.path`, `gateway` and
    `apps.gateway` are **two distinct module objects with separate class identities** — the
    `SymonClient` ambiguity this repo already paid for is the general case, and anything
    holding module-global state or doing `isinstance` across both breaks silently.
    `api.py` running as a script is also why OpenAPI schema names come out as
    `__main____ImageRequest`.

    **Convert it before `SPLIT-API` stage 1, not after.** Stage 1 creates one
    `apps/<name>/main.py` per surface; written against a real package they use absolute
    imports from the start and the conversion is a no-op for them, rather than a second pass
    over every file stage 1 just created. It should land on its own commit, imports and
    nothing else. The six venvs are unaffected — they run as subprocesses with their own
    interpreters and do not import `backend`.

    Full costing, including what breaks: `review/commissioning-20260909/BACKEND-STRUCTURE-20260910.md`.

14. **There is still no dependency manifest for the serving path, but the facts now exist.**
    `backend/DEPENDENCIES.md` is prose and `restore/locks/*.lock.txt` pin the venvs; neither
    makes `backend` installable. Measured: **196 distributions in the serving interpreter —
    195 dpkg, 1 pip**, that one being `xdg 5`, which nothing in this repository imports. Of the
    26 third-party import names the serving code uses, 14 resolve to a Debian `python3-*`
    package and 12 are deliberately absent because they live in a venv.

    A `pyproject.toml` is the missing piece and it **depends on bite 13** — there is no package
    to describe yet. One policy question is the owner's before it can be written: `api.py`'s
    docstring says the serving path runs on system dist-packages *deliberately*, so the
    manifest should **declare** names and floors rather than pin versions, or it invites a venv
    that contradicts the stated policy.

### What is deliberately not done yet

The post-transfer stages are gated on the transfers finishing, in this order: Drive dedupe
(`tools/data/drive-dedupe.py`, after organization, per the spec), cross-root audit
(`tools/audit/cross_root_audit.py scan`), catalogue publication (`tools/data/drive_catalog.py build`
then `upload`), then repository closure — final commit, manifests, tests, `git fsck`, one
bundle regeneration, clone, restore-verify. **Do not regenerate the bundle before the
tracked storage changes stop.**

`symoneural-api` remains deliberately stopped. Do not start it to manufacture green smoke
output; the verified 14/14 capture is preserved.

## Current handoff — 2026-09-08 (late), restore control plane + disk reckoning

**Next executor: any coding agent or person.** The next task is **the coder training corpus**,
and it does not exist yet -- see item 5 below. This entry supersedes the older pointers
preserved further down.

**State at handoff.** HEAD `2eb03803`, branch main, tree clean, 0 staged, 0 stashed. Suite
**2400 passed / 0 failed / 56 skipped**, recorded in `run/SUITE-LAST.txt` and read from there
rather than typed. `RESTORE_VERIFY=PASS` over 81 rows. `symoneural-web` active and enabled
serving :80/:443; **`symoneural-api` is STOPPED** at the owner's request (enabled, so a reboot
restores it); `symoneural-gateway` inactive and disabled, source intact. Full detail in
`ProjectStatus.md` under *Current state → 2026-09-08 (late)*; this entry says only what will
bite you.

**What will bite you.**

1. **11 of the 14 restore smokes need `symoneural-api` running.** It is stopped. Start it
   (`sudo systemctl start symoneural-api`) before `restore/symoneural-restore smoke all`, or
   read the canonical 14/14 capture at `.private/rehearsal/SMOKE-RUN-r20260908.txt`, taken
   while it was up.

2. **The installed `symoneural-api` and `symoneural-gateway` units are STALE against their
   templates.** `StartLimitIntervalSec`/`StartLimitBurst` still sit in `[Service]`, where
   systemd silently ignores them -- so the crash-loop protection their own comments describe
   has never once applied. `SERVICES.tsv` records this as DIVERGED. Reinstalling alters a
   production service and that authority was not granted; it is the owner's call.

3. **`symoneural-web` has no fallback.** It owns :80 and :443 and `caddy.service` is
   *disabled*. The restore plan must never `systemctl start caddy` -- `symoneural-web.service`
   declares `Conflicts=caddy.service`, so starting the vendor unit makes systemd **stop the
   production web server**. That defect was in RESTORE-ORDER step 90 and is fixed; do not
   reintroduce it. The Caddyfile is configuration consumed by symoneural-web, not a unit.

4. **`/yocto/artifacts` is the only surviving copy** of 248 GB de-duplicated out of `/home`.
   Until it is verified on Drive, do not touch `/yocto`. `YOCTO_WIPE_READY=NO`.

5. **"Train the SyMoNeuRaL Coder" has no corpus.** `training/train_lora.py` is real and good,
   but its own docstring says it turns a stock Qwen into the **admin/persona** model, and
   `training/corpus.jsonl` is 327 identity examples. Running it trains the persona adapter
   again beside the two that exist. A coder corpus is real work that has not been started;
   do not report a persona run as coder training.

6. **`symoneural-diffuse` links an ABSOLUTE CUDA path**, not `$ORIGIN` like the other
   engines: `/usr/local/cuda-13.3/targets/x86_64-linux/lib`. Measured on both the production
   and rebuilt artefacts, so it is by design. A restored machine without CUDA at that exact
   path builds the image engine successfully and then fails to load it at run time -- which
   surfaces only when a visitor asks for an image.

7. **`symoneural-web` needs Go >= 1.25.1.** This host bootstraps 1.24.4 and `GOTOOLCHAIN=auto`
   silently fetches the newer toolchain as a module. With `GOTOOLCHAIN=local` the build
   **fails**. Provision Go explicitly rather than relying on the auto-download.

8. **Rotate the provider credentials.** Seven keys sat at mode 0664 -- world-readable -- and
   are now at `.private/secrets/` 0600. `GITHUB_TOKEN` and `HF_TOKEN` do not expire on their
   own, and the machine they sat on is being decommissioned.

## Earlier handoffs

Everything before 2026-09-08 is in **`docs/history/handoffs/HANDOVER-ARCHIVE-pre-20260908.md`** —
4,876 lines of accreted history, kept verbatim and clearly marked as
historical. It was split out because a canonical handoff that grows by prepending stops being
a handoff, and because present-tense audit checks cannot tell a 2026-08 statement from a
claim about today. The dated per-window handoffs are in `docs/history/handoffs/`.
