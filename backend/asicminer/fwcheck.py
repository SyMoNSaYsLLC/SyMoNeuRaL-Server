#!/usr/bin/env python3
"""Pre-flight a Bitmain firmware package the way the miner's own `runme.sh` will.

Flashing a package that fails verification costs an hour and, at worst, a rig. The check
that decides it is a 40-line shell script *inside the package*, and it runs on the miner
after the upload -- by which point you are already committed. This runs the same checks
here, before anything is pushed, and reports the exact exit code `runme.sh` would produce.

## The package format, confirmed against the real archives

A signed Antminer package is a tarball of seven files:

    cert.pem  cert.pem.sig  fw.tar.gz  fw.tar.gz.sig  runme.sh  runme.sh.sig  version_number

`cert.pem` is a bare RSA public key -- **not** an X.509 certificate, despite the name and
the `.pem` extension, so `openssl x509` on it fails and that failure means nothing. The
signatures are raw RSA over SHA-256; at RSA-4096 they are 512 bytes.

## What runme.sh actually checks, in order, with its own exit codes

    1  cert.pem missing
    2  cert.pem.sig missing
    3  cert.pem fails to verify against /etc/bitmain-pub.pem   <-- CONDITIONAL, see below
    4  fw.tar.gz.sig missing
    5  fw.tar.gz fails to verify against cert.pem

**Step 3 only runs `if [ -e /etc/bitmain-pub.pem ]`.** That conditional is the whole story
for custom firmware: a miner that still has Bitmain's public key on disk requires the
package's cert to be signed by Bitmain, so a self-signed package is rejected. Custom
firmware images generally do not ship that file, so on a rig already running one, step 3 is
skipped entirely -- but **step 5 always runs**, against the `cert.pem` inside the package
itself. So a repackager self-signs with their own key and the chain is internally
consistent.

The practical consequence, and the reason this tool reports the two separately: step 5 is
checkable here with certainty, and step 3 depends on the state of the target rig. Reporting
one number for both would be a guess presented as a verdict.

    python3 fwcheck.py <package.tar.gz> [--bitmain-pub /path/to/bitmain-pub.pem]

Prints JSON. Exit 0 means the tool ran, not that the package passed -- read `would_pass`.
Nothing is extracted outside a temporary directory and nothing is ever executed: the inner
`runme.sh` is read and reported on, never run.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import subprocess
import sys
import tarfile
import tempfile

REQUIRED = ["cert.pem", "cert.pem.sig", "fw.tar.gz", "fw.tar.gz.sig"]
EXPECTED = REQUIRED + ["runme.sh", "runme.sh.sig", "version_number"]

# runme.sh's own exit codes, so the report speaks the miner's language rather than ours.
CODES = {
    1: "cert.pem missing from the package",
    2: "cert.pem.sig missing from the package",
    3: "cert.pem is not signed by Bitmain's key (only checked on rigs that still have "
       "/etc/bitmain-pub.pem)",
    4: "fw.tar.gz.sig missing from the package",
    5: "fw.tar.gz does not verify against the package's own cert.pem",
}


def _openssl_verify(pub: pathlib.Path, sig: pathlib.Path, payload: pathlib.Path) -> bool:
    """One `openssl dgst -sha256 -verify`, exactly as runme.sh invokes it."""
    if not (pub.is_file() and sig.is_file() and payload.is_file()):
        return False
    r = subprocess.run(
        ["openssl", "dgst", "-sha256", "-verify", str(pub), "-signature", str(sig),
         str(payload)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return r.returncode == 0


def _safe_extract(pkg: pathlib.Path, dest: pathlib.Path) -> list[str]:
    """Extract, refusing any member that would escape `dest`.

    A firmware package is an untrusted archive from the internet. `tar` happily writes
    `../../etc/cron.d/x` if a member says so, and this tool runs as whoever is checking the
    file. Python 3.12+ has `filter='data'` for exactly this; the manual check keeps the
    behaviour identical on older interpreters rather than depending on the version.
    """
    names = []
    with tarfile.open(pkg, "r:*") as tf:
        for m in tf.getmembers():
            p = (dest / m.name).resolve()
            if not str(p).startswith(str(dest.resolve()) + "/"):
                raise ValueError(f"archive member escapes the extraction directory: {m.name!r}")
            if m.issym() or m.islnk():
                raise ValueError(f"archive contains a link, refusing: {m.name!r}")
            names.append(m.name)
        try:
            tf.extractall(dest, filter="data")           # py3.12+
        except TypeError:
            tf.extractall(dest)                          # names already validated above
    return names


def check(pkg: pathlib.Path, bitmain_pub: pathlib.Path | None = None,
          blacklist: pathlib.Path | None = None) -> dict:
    out = {
        "package": pkg.name,
        "bytes": pkg.stat().st_size if pkg.is_file() else None,
        "contents": [], "missing": [], "unexpected": [],
        "version": None,
        "runme_md5": None, "runme_sig_present": None, "blacklisted": None,
        "fw_verifies_against_cert": None,   # runme.sh step 5 -- always runs on the rig
        "cert_signed_by_bitmain": None,     # step 3 -- only on rigs with the Bitmain key
        "would_pass": None,
        "would_exit": None,
        "verdict": "",
        "notes": [],
        "error": None,
    }
    if not pkg.is_file():
        out["error"] = f"no such file: {pkg}"
        return out
    if not shutil.which("openssl"):
        out["error"] = "openssl not on PATH; cannot verify signatures"
        return out

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="fwcheck-"))
    try:
        # The CGI rejects any tarball containing a symlink, before it reaches runme.sh:
        #   tar ztvf $$.tgz | grep "^l"   -> "tarball contains symbol link", upload aborted.
        # Report it as a gate rather than letting the extractor raise, because from the
        # operator's point of view it is a reason the upload will be refused, not a broken
        # file. (We refuse links too, for our own safety -- see _safe_extract.)
        try:
            with tarfile.open(pkg, "r:*") as tf:
                links = [m.name for m in tf.getmembers() if m.issym() or m.islnk()]
        except tarfile.TarError as e:
            out["error"] = f"not a readable tar package: {e}"
            return out
        if links:
            out.update(would_pass=False, would_exit=None,
                       verdict="upgrade.cgi rejects tarballs containing symlinks, before "
                               "runme.sh runs")
            out["contents"] = links
            return out

        try:
            out["contents"] = sorted(_safe_extract(pkg, tmp))
        except (tarfile.TarError, ValueError) as e:
            out["error"] = f"not a readable tar package: {e}"
            return out

        # upgrade.cgi md5s the outer runme.sh and refuses it if the hash appears in
        # /etc/blacklist on the rig -- a list of installers Bitmain has revoked. It sits
        # BEFORE runme.sh runs, so a package can be perfectly signed and still be refused.
        # The 2019 S17 Pro rootfs ships 27 entries. Pass --blacklist to check against a
        # copy pulled off your own rig; without one this is reported, not evaluated.
        rm = tmp / "runme.sh"
        if rm.is_file():
            import hashlib
            out["runme_md5"] = hashlib.md5(rm.read_bytes()).hexdigest()
        # The CGI also verifies runme.sh.sig against /etc/bitmain-pub.pem before running it.
        # That is why runme.sh.sig is in the package at all -- runme.sh never checks itself.
        out["runme_sig_present"] = (tmp / "runme.sh.sig").is_file()

        if blacklist and blacklist.is_file() and out["runme_md5"]:
            banned = {l.strip() for l in blacklist.read_text().split() if l.strip()}
            out["blacklisted"] = out["runme_md5"] in banned
            if out["blacklisted"]:
                out["notes"].append(
                    "This runme.sh is in the rig's /etc/blacklist. upgrade.cgi refuses it "
                    "before any signature check, however well-formed the package is.")

        out["missing"] = [f for f in REQUIRED if not (tmp / f).is_file()]
        out["unexpected"] = [f for f in out["contents"] if f not in EXPECTED]
        vn = tmp / "version_number"
        if vn.is_file():
            out["version"] = vn.read_text().strip()

        # Missing files short-circuit, in runme.sh's own order.
        for name, code in (("cert.pem", 1), ("cert.pem.sig", 2), ("fw.tar.gz.sig", 4)):
            if not (tmp / name).is_file():
                out.update(would_pass=False, would_exit=code, verdict=CODES[code])
                return out
        if not (tmp / "fw.tar.gz").is_file():
            out.update(would_pass=False, would_exit=5,
                       verdict="fw.tar.gz missing from the package")
            return out

        # Step 5 -- the one that always runs, so the one we can be certain about.
        out["fw_verifies_against_cert"] = _openssl_verify(
            tmp / "cert.pem", tmp / "fw.tar.gz.sig", tmp / "fw.tar.gz")

        # Step 3 -- only meaningful with Bitmain's public key to hand.
        if bitmain_pub and bitmain_pub.is_file():
            out["cert_signed_by_bitmain"] = _openssl_verify(
                bitmain_pub, tmp / "cert.pem.sig", tmp / "cert.pem")
        else:
            out["notes"].append(
                "No Bitmain public key supplied, so step 3 was not evaluated. On a rig that "
                "still has /etc/bitmain-pub.pem an unsigned or self-signed cert exits 3; on "
                "a rig already running custom firmware that file is usually absent and the "
                "step is skipped. Pass --bitmain-pub to check it.")

        if not out["fw_verifies_against_cert"]:
            out.update(would_pass=False, would_exit=5, verdict=CODES[5])
        elif out["cert_signed_by_bitmain"] is False:
            out.update(would_pass=False, would_exit=3, verdict=CODES[3])
        else:
            out["would_pass"] = True
            out["would_exit"] = 0
            out["verdict"] = ("passes every check this package can be judged on"
                             + ("" if out["cert_signed_by_bitmain"]
                                else "; step 3 depends on the target rig — see notes"))
        if out["unexpected"]:
            out["notes"].append(
                f"Package carries files runme.sh does not expect: {out['unexpected']}. Not "
                "fatal — runme.sh ignores them — but worth knowing what you are flashing.")
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def check_sd(pkg: pathlib.Path) -> dict:
    """Pre-flight an SD-card recovery package against its own `readme.factory` manifest.

    A different format entirely from the browser path: a zip, per-file 256-byte (RSA-2048)
    signatures rather than one 512-byte chain, and no runme.sh. `readme.factory` looks like
    documentation and is actually a `sha256sum` manifest, which makes it checkable.

    Worth checking every time, because an SD image is what you reach for when a rig is
    *already* bricked. The S19j package in external/ fails five of its own nine hashes.
    """
    import zipfile
    out = {"package": pkg.name, "kind": "sd-card", "files": [], "manifest": None,
           "ok": [], "failed": [], "unlisted": [], "would_pass": None, "error": None}
    if not pkg.is_file():
        out["error"] = f"no such file: {pkg}"
        return out

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="fwcheck-sd-"))
    try:
        try:
            with zipfile.ZipFile(pkg) as z:
                bad = z.testzip()
                if bad:
                    out["error"] = f"archive is corrupt at {bad}"
                    return out
                for n in z.namelist():
                    if (tmp / n).resolve().is_relative_to(tmp.resolve()):
                        z.extract(n, tmp)
                out["files"] = sorted(z.namelist())
        except zipfile.BadZipFile as e:
            out["error"] = f"not a readable zip: {e}"
            return out

        man = tmp / "readme.factory"
        if not man.is_file():
            out["error"] = "no readme.factory manifest in this package"
            return out
        out["manifest"] = "readme.factory"

        import hashlib
        listed = set()
        for line in man.read_text().splitlines():
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            want, name = parts[0], parts[1].strip().lstrip("./")
            listed.add(name)
            f = tmp / name
            if not f.is_file():
                out["failed"].append({"file": name, "why": "listed but not in the archive"})
                continue
            got = hashlib.sha256(f.read_bytes()).hexdigest()
            (out["ok"] if got == want else out["failed"]).append(
                {"file": name} if got == want
                else {"file": name, "want": want, "got": got})
        out["unlisted"] = sorted(
            n for n in out["files"]
            if n not in listed and not n.endswith("/") and n != "readme.factory")
        out["would_pass"] = not out["failed"]
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="Pre-flight a Bitmain firmware package.")
    ap.add_argument("package", type=pathlib.Path)
    ap.add_argument("--bitmain-pub", type=pathlib.Path, default=None,
                    help="Bitmain public key, to evaluate runme.sh step 3 as well")
    ap.add_argument("--blacklist", type=pathlib.Path, default=None,
                    help="a copy of /etc/blacklist from the target rig; upgrade.cgi refuses "
                         "any runme.sh whose md5 is listed, before checking signatures")
    ap.add_argument("--sd", action="store_true",
                    help="treat this as an SD-card recovery zip, checked against readme.factory")
    ap.add_argument("--microbt", action="store_true",
                    help="treat this as a MicroBT/Whatsminer .bin -- container header only, "
                         "because the payload is encrypted")
    a = ap.parse_args()
    # Guess by content when not told, so the common case needs no flag -- but a flag wins,
    # because a mis-detected format silently checks the wrong thing.
    #
    # `sd = a.sd or (not a.sd and pkg_is_zip(...))` was the old line. The second clause can
    # never change the result: `or` only evaluates it when `a.sd` is already false, so
    # `not a.sd` is always true there. It read as if it did something.
    if a.microbt or (not a.sd and is_microbt(a.package)):
        out = check_microbt(a.package)
    elif a.sd or pkg_is_zip(a.package):
        out = check_sd(a.package)
    else:
        out = check(a.package, a.bitmain_pub, a.blacklist)
    print(json.dumps(out, indent=2))
    return 0


def is_microbt(p: pathlib.Path) -> bool:
    """MicroBT .bin, recognised by its four-byte magic rather than by its extension."""
    try:
        with p.open("rb") as f:
            return int.from_bytes(f.read(4), "little") == MICROBT_MAGIC
    except OSError:
        return False


def pkg_is_zip(p: pathlib.Path) -> bool:
    try:
        with p.open("rb") as f:
            return f.read(2) == b"PK"
    except OSError:
        return False



# ---------------------------------------------------------------- MicroBT / Whatsminer

MICROBT_MAGIC = 0xAE640A3F      # little-endian, first four bytes


def check_microbt(pkg: pathlib.Path) -> dict:
    """Validate what can be validated about a Whatsminer .bin.

    Which is the container header and nothing else, because **the payload is encrypted**.
    Measured on Whatsminer-all-20260416.14: entropy is 7.999 bits/byte from the first byte
    after the header to the end of a 41 MB file -- indistinguishable from random. Scanning
    for gzip/squashfs/UBI/JFFS2/ext/xz/cramfs magic finds only coincidental byte pairs with
    no valid structure behind them, which is exactly what random data produces.

    That is a real difference from Bitmain, not a gap in this tool. An Antminer package is a
    plain signed tarball that `tar` opens, so its runme.sh, version gate and NAND writes can
    all be read before flashing. A Whatsminer image cannot be opened at all without MicroBT's
    key, so there is no equivalent of the runme.sh pre-flight, and no way to emulate it --
    you cannot extract a kernel from ciphertext.

    What the header does carry, in the clear, is the **control board type** as ASCII. That is
    worth checking: flashing an image built for one board to another is the mistake this can
    actually catch.
    """
    import struct
    out = {"package": pkg.name, "kind": "microbt", "magic_ok": None, "board": None,
           "declared_payload": None, "header_bytes": None, "size_consistent": None,
           "payload_encrypted": None, "would_pass": None, "notes": [], "error": None}
    if not pkg.is_file():
        out["error"] = f"no such file: {pkg}"
        return out
    size = pkg.stat().st_size
    with pkg.open("rb") as fh:
        head = fh.read(0x40)
        if len(head) < 0x40:
            out["error"] = "file is too short to hold a header"
            return out
        magic = struct.unpack("<I", head[0:4])[0]
        out["magic_ok"] = (magic == MICROBT_MAGIC)
        if not out["magic_ok"]:
            out.update(would_pass=False,
                       error=f"magic 0x{magic:08x}, expected 0x{MICROBT_MAGIC:08x} -- "
                             "not a Whatsminer image (a failed download saved as .bin "
                             "usually starts with '<' or is empty)")
            return out
        out["board"] = head[0x28:0x38].split(b"\x00")[0].decode("ascii", "replace") or None
        out["declared_payload"] = struct.unpack("<I", head[0x10:0x14])[0]
        out["header_bytes"] = struct.unpack("<I", head[0x38:0x3c])[0]
        out["size_consistent"] = (out["declared_payload"] + out["header_bytes"] == size)

        # Entropy of one block well inside the payload. Encrypted is the expected answer;
        # anything much below 7.9 would mean this image is NOT like the one measured, which
        # is worth knowing rather than assuming.
        import collections, math
        fh.seek(min(out["header_bytes"] + 1_000_000, max(0, size - 262144)))
        blk = fh.read(262144)
        if blk:
            c = collections.Counter(blk); n = len(blk)
            e = -sum((v / n) * math.log2(v / n) for v in c.values())
            out["payload_encrypted"] = e > 7.9
            out["notes"].append(f"payload entropy {e:.3f} bits/byte"
                                + (" -- encrypted or compressed, cannot be opened"
                                   if e > 7.9 else " -- NOT opaque, worth a closer look"))

    if not out["size_consistent"]:
        out["notes"].append(
            f"declared payload {out['declared_payload']:,} + header {out['header_bytes']:,} "
            f"!= file {size:,}; the image is truncated or padded")
    out["notes"].append(
        f"board is '{out['board']}'. Flashing this to a different control board is the "
        "failure this check exists for -- MicroBT ships one .bin covering several models, "
        "but only for the board named here.")
    out["would_pass"] = bool(out["magic_ok"] and out["size_consistent"])
    return out


# The entry point is the LAST thing in this file, and that is load-bearing. It used to sit
# above `check_microbt`, and `if __name__ == "__main__"` runs during module execution --
# so `main()` was called before `check_microbt` and `MICROBT_MAGIC` existed, and dispatching
# to them from the CLI would have raised NameError rather than working. The Whatsminer
# checker was reachable only by importing this file as a library, which nothing did.
if __name__ == "__main__":
    sys.exit(main())
