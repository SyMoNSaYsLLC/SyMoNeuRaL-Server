# SPDX-License-Identifier: LicenseRef-SyMoNeuRaL-Proprietary
# Copyright (c) 2026 SymonSays LLC. All rights reserved.
"""Interruption/resume tests for `tools/data/storage_reorg.py`.

Every one of these covers a state the storage reorganisation actually stopped in, and each
asserts the thing that costs real money to get wrong: that resuming does NOT re-send bytes
over a ~5 MB/s link, and that a source is never retired on the strength of an unconfirmed
destination.

The tests drive the state machine directly with a fake remote. They never touch Drive and
never touch the real `.private/storage-reorg` ledger -- module paths are redirected into
`tmp_path` first, so a test run cannot disturb a live migration.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

REPO = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())


def _load(tmp: pathlib.Path):
    """Load storage_reorg with all of its state redirected into a temp tree."""
    spec = importlib.util.spec_from_file_location(
        "storage_reorg_under_test", REPO / "tools" / "data" / "storage_reorg.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.ROOT = tmp
    m.STATE_DIR = tmp / ".private" / "storage-reorg"
    m.STATE = m.STATE_DIR / "state.json"
    m.OPS = m.STATE_DIR / "operations.tsv"
    m.VERIFY_DIR = m.STATE_DIR / "verification"
    m.LOCK = m.STATE_DIR / "owner.lock"
    m.STAGE = tmp / ".private" / "offload-stage"
    m.STAGE.mkdir(parents=True, exist_ok=True)
    m.STATE_DIR.mkdir(parents=True, exist_ok=True)
    m.VERIFY_DIR.mkdir(parents=True, exist_ok=True)
    return m


class Spy:
    """Stands in for every outbound side effect, and counts what was attempted."""

    def __init__(self, remote: dict[str, str]):
        self.remote = remote
        self.uploads: list[str] = []
        self.packs = 0

    def remote_md5(self, path: str):
        return self.remote.get(path)

    def sh(self, args, timeout=0):
        import subprocess
        if args and args[0] == "rclone" and len(args) > 1 and args[1] == "copy":
            self.uploads.append(args[2])
        if args and args[0] == "tar":
            self.packs += 1
        return subprocess.CompletedProcess(args, 0, "", "")


def _wire(m, spy, monkeypatch):
    monkeypatch.setattr(m, "remote_md5", spy.remote_md5)
    monkeypatch.setattr(m, "sh", spy.sh)
    monkeypatch.setattr(m, "du_bytes", lambda p: 4096)
    # A real content manifest needs a real tree; these tests assert transitions, not
    # manifest contents (test_content_manifest_is_content_addressed covers that).
    monkeypatch.setattr(m, "write_manifest", lambda src, out: (out.write_text(
        "TYPE\tRELPATH\tSIZE_BYTES\tSHA256\tMODE\tLINK_TARGET\n"), (1, 4096))[1])


def _src(tmp: pathlib.Path, name="leaf") -> pathlib.Path:
    d = tmp / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "payload.bin").write_bytes(b"payload")
    return d


def test_complete_is_never_replayed(tmp_path, monkeypatch):
    m = _load(tmp_path)
    spy = Spy({})
    _wire(m, spy, monkeypatch)
    src = _src(tmp_path)
    st = {"ops": {"op": {"state": "COMPLETE"}}}

    assert m._pack_upload_retire("op", src, "Dest", "why", st) is True
    assert spy.uploads == [], "a COMPLETE operation must not re-upload"
    assert spy.packs == 0, "a COMPLETE operation must not repack"
    assert src.exists(), "a COMPLETE operation must not re-retire anything"


def test_failed_fails_closed_and_leaves_source(tmp_path, monkeypatch):
    m = _load(tmp_path)
    spy = Spy({})
    _wire(m, spy, monkeypatch)
    src = _src(tmp_path)
    st = {"ops": {"op": {"state": "FAILED", "detail": "upload rc=1"}}}

    assert m._pack_upload_retire("op", src, "Dest", "why", st) is False
    assert src.exists(), "a FAILED operation must never retire its source"
    assert spy.uploads == [], "a FAILED operation must not silently retry destructively"


def test_dest_verified_retires_without_repack_or_reupload(tmp_path, monkeypatch):
    """The expensive one: 5 GB already verified on Drive must not be sent twice."""
    m = _load(tmp_path)
    spy = Spy({"Dest/leaf.tar.zst": "abc123"})
    _wire(m, spy, monkeypatch)
    src = _src(tmp_path)
    st = {"ops": {"op": {"state": "DEST_VERIFIED", "dest": "Dest/leaf.tar.zst",
                         "remote_md5": "abc123", "raw_bytes": 4096}}}

    assert m._pack_upload_retire("op", src, "Dest", "why", st) is True
    assert spy.uploads == [], "DEST_VERIFIED resume must not re-upload"
    assert spy.packs == 0, "DEST_VERIFIED resume must not repack"
    assert not src.exists(), "DEST_VERIFIED resume must retire the source"
    assert st["ops"]["op"]["state"] == "COMPLETE"


def test_dest_verified_but_remote_changed_keeps_source(tmp_path, monkeypatch):
    m = _load(tmp_path)
    spy = Spy({"Dest/leaf.tar.zst": "DIFFERENT"})
    _wire(m, spy, monkeypatch)
    src = _src(tmp_path)
    st = {"ops": {"op": {"state": "DEST_VERIFIED", "dest": "Dest/leaf.tar.zst",
                         "remote_md5": "abc123", "raw_bytes": 4096}}}

    assert m._pack_upload_retire("op", src, "Dest", "why", st) is False
    assert src.exists(), "a destination that no longer matches must not retire the source"
    assert st["ops"]["op"]["state"] == "FAILED"


def test_uploading_promotes_when_remote_already_holds_the_object(tmp_path, monkeypatch):
    """Interrupted mid-upload, but the object landed: promote, do not re-send."""
    m = _load(tmp_path)
    src = _src(tmp_path)
    staged = m.STAGE / "leaf.tar.zst"
    staged.write_bytes(b"artifact-bytes")
    real_md5 = m.md5_of(staged)
    spy = Spy({"Dest/leaf.tar.zst": real_md5})
    _wire(m, spy, monkeypatch)
    st = {"ops": {"op": {"state": "UPLOADING", "dest": "Dest/leaf.tar.zst",
                         "local_md5": real_md5, "raw_bytes": 4096}}}

    assert m._pack_upload_retire("op", src, "Dest", "why", st) is True
    assert spy.uploads == [], "UPLOADING resume must not re-upload a complete object"
    assert spy.packs == 0
    assert not src.exists()
    assert st["ops"]["op"]["state"] == "COMPLETE"


def test_source_retired_closes_out_when_destination_reconfirms(tmp_path, monkeypatch):
    m = _load(tmp_path)
    spy = Spy({"Dest/leaf.tar.zst": "abc123"})
    _wire(m, spy, monkeypatch)
    src = tmp_path / "leaf"          # already gone, which is what SOURCE_RETIRED means
    st = {"ops": {"op": {"state": "SOURCE_RETIRED", "dest": "Dest/leaf.tar.zst",
                         "remote_md5": "abc123"}}}

    assert m._pack_upload_retire("op", src, "Dest", "why", st) is True
    assert st["ops"]["op"]["state"] == "COMPLETE"
    assert spy.uploads == []


def test_source_retired_with_lost_destination_is_flagged_not_hidden(tmp_path, monkeypatch):
    """Source gone AND destination gone is the one unrecoverable shape. It must be loud."""
    m = _load(tmp_path)
    spy = Spy({})
    _wire(m, spy, monkeypatch)
    src = tmp_path / "leaf"
    st = {"ops": {"op": {"state": "SOURCE_RETIRED", "dest": "Dest/leaf.tar.zst",
                         "remote_md5": "abc123"}}}

    assert m._pack_upload_retire("op", src, "Dest", "why", st) is False
    assert st["ops"]["op"]["state"] == "FAILED"


def test_unrouted_leaf_is_left_in_place(tmp_path, monkeypatch):
    """A leaf the route table does not name is unclassified. It must stay put and be
    reported, never swept into a default bucket."""
    m = _load(tmp_path)
    spy = Spy({})
    _wire(m, spy, monkeypatch)
    parent = tmp_path / "tree"
    (parent / "known").mkdir(parents=True)
    (parent / "unknown").mkdir(parents=True)
    (parent / "unknown" / "f").write_bytes(b"x")
    calls: list[str] = []
    monkeypatch.setattr(m, "_pack_upload_retire",
                        lambda oid, s, d, w, st, retire=True: calls.append(s.name) or True)
    st = {"ops": {}}
    m.do_move_leaves({"id": "op", "src": str(parent), "routes": {"known": "Dest"},
                      "why": "w"}, st, apply=True)

    assert calls == ["known"]
    assert (parent / "unknown").exists(), "an unrouted leaf must not be moved"


def test_content_manifest_is_content_addressed_not_size_only(tmp_path):
    """The manifest must carry SHA256 and must not dereference symlinks -- size alone
    cannot distinguish two same-length files, so a size-only manifest cannot support
    dedupe or prove an archived collection is what it claims."""
    import subprocess
    src = tmp_path / "leaf"
    src.mkdir()
    (src / "a.txt").write_bytes(b"AAAA")
    (src / "b.txt").write_bytes(b"BBBB")          # same size, different content
    (src / "link").symlink_to("a.txt")
    out = tmp_path / "CONTENTS.tsv"
    r = subprocess.run(["python3", str(REPO / "tools" / "lib" / "sym_content_manifest.py"),
                        "make", str(src), str(out)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    rows = [l.split("\t") for l in out.read_text().splitlines()[1:]]
    by = {r[1]: r for r in rows}
    assert "SHA256" in out.read_text().splitlines()[0]
    assert by["a.txt"][3] != by["b.txt"][3], "equal-size files must hash differently"
    assert by["a.txt"][2] == by["b.txt"][2] == "4"
    assert by["link"][0] == "SYMLINK", "symlinks must be recorded, not followed"
    assert by["link"][5] == "a.txt", "the link target itself is the identity"


# =========================================================================================
# tools/data/drive-dedupe.py survivor selection
# =========================================================================================
# This function decides which copy is DELETED, so it gets tests. Path length alone used to
# decide it, and that is backwards now the semantic collections exist: a stray copy loose
# at the Drive root would have outranked the correctly-filed one inside a collection.

def _dedupe():
    spec = importlib.util.spec_from_file_location(
        "drive_dedupe_under_test", REPO / "tools" / "drive-dedupe.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_survivor_prefers_a_canonical_collection_over_a_shallower_path():
    m = _dedupe()
    paths = ["stray-copy.zip", "Symoneural/History/Source-Snapshots/stray-copy.zip"]
    assert m.survivor(paths) == "Symoneural/History/Source-Snapshots/stray-copy.zip", \
        "the filed copy must outrank a loose root copy even though the root path is shorter"


def test_survivor_prefers_earlier_taxonomy_rank():
    m = _dedupe()
    paths = ["Historical-Archive/a/x.zip", "Symoneural/a/x.zip"]
    assert m.survivor(paths) == "Symoneural/a/x.zip"


def test_survivor_breaks_ties_shallower_then_alphabetically_and_is_deterministic():
    m = _dedupe()
    paths = ["Projects/b/deep/deeper/x.zip", "Projects/a/x.zip", "Projects/b/x.zip"]
    first = m.survivor(paths)
    assert first == "Projects/a/x.zip"
    # Determinism matters: a dry run and the real run must not disagree about which copy
    # lives, or the plan the operator approved is not the plan that executes.
    assert m.survivor(list(reversed(paths))) == first


def test_restore_and_upstream_prefixes_are_protected_from_dedupe():
    m = _dedupe()
    rows = [
        {"Path": "Symoneural/Restore-Recovery/bundle.tar", "Size": 5 << 20,
         "Hashes": {"md5": "same"}},
        {"Path": "Symoneural/Upstream-Source/p/abc123/src.tar", "Size": 5 << 20,
         "Hashes": {"md5": "same"}},
        {"Path": "Projects/copy-a.tar", "Size": 5 << 20, "Hashes": {"md5": "other"}},
        {"Path": "Projects/copy-b.tar", "Size": 5 << 20, "Hashes": {"md5": "other"}},
    ]
    g = m.groups(rows)
    flat = [p for v in g.values() for p in v]
    assert not any(p.startswith("Symoneural/Restore-Recovery/") for p in flat), \
        "restore material must never enter a dedupe group"
    assert not any(p.startswith("Symoneural/Upstream-Source/") for p in flat), \
        "revision-keyed upstream snapshots are immutable by design, not waste"
    assert sorted(flat) == ["Projects/copy-a.tar", "Projects/copy-b.tar"]


def test_files_below_one_mebibyte_are_ignored():
    m = _dedupe()
    rows = [{"Path": f"Projects/tiny-{i}.txt", "Size": 1024, "Hashes": {"md5": "z"}}
            for i in range(3)]
    assert m.groups(rows) == {}, \
        "thousands of identical .gitkeep/__init__.py copies free nothing and break trees"


# =========================================================================================
# Drive-merge collision rules
# =========================================================================================
# A bare moveto into an occupied path is how one of two same-named objects silently becomes
# the only one. Drive also permits two entries with the same NAME at one path, so "the
# destination exists" is a different question from "this is the same object".

def test_drive_children_deletes_a_verified_duplicate_instead_of_overwriting(
        tmp_path, monkeypatch):
    m = _load(tmp_path)
    calls: list[list[str]] = []

    def fake_sh(args, timeout=0):
        import subprocess
        calls.append(args)
        if args[:2] == ["rclone", "lsjson"] and "--stat" in args:
            # both source and destination report the same size and md5
            return subprocess.CompletedProcess(
                args, 0, '{"Name":"x.zip","Size":100,"Hashes":{"md5":"aaa"}}', "")
        if args[:2] == ["rclone", "lsjson"]:
            return subprocess.CompletedProcess(
                args, 0, '[{"Name":"x.zip","Size":100,"IsDir":false}]', "")
        return subprocess.CompletedProcess(args, 0, '{"bytes":100,"count":1}', "")

    monkeypatch.setattr(m, "sh", fake_sh)
    st = {"ops": {}}
    m.do_drive_children({"id": "op", "src": "Bucket",
                         "classify": lambda n, d: "Dest", "why": "w"}, st, apply=True)
    verbs = [c[1] for c in calls if c[0] == "rclone"]
    assert "deletefile" in verbs, "a byte-identical duplicate must be deleted, not moved"
    assert "moveto" not in verbs, "it must not be moved on top of the survivor"
    assert st["ops"]["op::x.zip"]["state"] == "COMPLETE"
    assert "duplicate" in st["ops"]["op::x.zip"]["detail"]


def test_drive_children_preserves_both_when_content_differs(tmp_path, monkeypatch):
    m = _load(tmp_path)
    moves: list[str] = []

    def fake_sh(args, timeout=0):
        import subprocess
        if args[:2] == ["rclone", "lsjson"] and "--stat" in args:
            # destination and source differ in md5
            md5 = "bbb" if "Dest/" in args[2] else "aaa"
            return subprocess.CompletedProcess(
                args, 0, '{"Name":"x.zip","Size":100,"Hashes":{"md5":"%s"}}' % md5, "")
        if args[:2] == ["rclone", "lsjson"]:
            return subprocess.CompletedProcess(
                args, 0, '[{"Name":"x.zip","Size":100,"IsDir":false}]', "")
        if args[:2] == ["rclone", "moveto"]:
            moves.append(args[3])
            return subprocess.CompletedProcess(args, 0, "", "")
        return subprocess.CompletedProcess(args, 0, '{"bytes":100,"count":1}', "")

    monkeypatch.setattr(m, "sh", fake_sh)
    st = {"ops": {}}
    m.do_drive_children({"id": "op", "src": "Bucket",
                         "classify": lambda n, d: "Dest", "why": "w"}, st, apply=True)
    assert moves, "a differing object must still be moved"
    assert "__from_" in moves[0] and "__src_" in moves[0], \
        "it must land under provenance-aware naming, not overwrite the destination"


# =========================================================================================
# Directory-to-directory Drive merges
# =========================================================================================
# `rclone moveto` onto an existing directory does not implement this project's merge
# policy, so the tree is walked explicitly. These tests drive that walk against a fake
# remote with real nesting, because the failure they guard against -- silently losing one
# of two same-named subtrees -- is invisible in a single-level test.

class FakeDrive:
    """A minimal Drive: {path: {"dir":bool, "size":int, "md5":str}}."""

    def __init__(self, entries: dict):
        self.e = dict(entries)
        self.moves: list[tuple[str, str]] = []
        self.deletes: list[str] = []
        self.rmdirs: list[str] = []

    # -- helpers ------------------------------------------------------------------------
    def _children(self, path: str):
        pre = path + "/"
        out = []
        for p, meta in self.e.items():
            if not p.startswith(pre):
                continue
            rest = p[len(pre):]
            if "/" in rest:
                continue
            out.append({"Name": rest, "IsDir": meta["dir"], "Size": meta.get("size", 0),
                        "Hashes": ({"md5": meta["md5"]} if meta.get("md5") else {})})
        return out

    def sh(self, args, timeout=0):
        import json as _j
        import subprocess
        if args[0] != "rclone":
            return subprocess.CompletedProcess(args, 0, "", "")
        verb = args[1]
        path = args[2].split(":", 1)[1] if ":" in args[2] else args[2]
        if verb == "lsjson":
            if "--stat" in args:
                m = self.e.get(path)
                if m is None:
                    return subprocess.CompletedProcess(args, 1, "", "not found")
                return subprocess.CompletedProcess(args, 0, _j.dumps(
                    {"Name": path.rsplit("/", 1)[-1], "IsDir": m["dir"],
                     "Size": m.get("size", 0),
                     "Hashes": ({"md5": m["md5"]} if m.get("md5") else {})}), "")
            if path not in self.e:
                return subprocess.CompletedProcess(args, 1, "", "not found")
            return subprocess.CompletedProcess(args, 0, _j.dumps(self._children(path)), "")
        if verb == "moveto":
            dst = args[3].split(":", 1)[1]
            self.moves.append((path, dst))
            sub = {p: v for p, v in self.e.items() if p == path or p.startswith(path + "/")}
            for p, v in sub.items():
                self.e.pop(p)
                self.e[dst + p[len(path):]] = v
            return subprocess.CompletedProcess(args, 0, "", "")
        if verb == "deletefile":
            self.deletes.append(path)
            self.e.pop(path, None)
            return subprocess.CompletedProcess(args, 0, "", "")
        if verb == "rmdir":
            self.rmdirs.append(path)
            self.e.pop(path, None)
            return subprocess.CompletedProcess(args, 0, "", "")
        return subprocess.CompletedProcess(args, 0, '{"bytes":0,"count":0}', "")


def _merge(tmp_path, monkeypatch, entries):
    m = _load(tmp_path)
    fd = FakeDrive(entries)
    monkeypatch.setattr(m, "sh", fd.sh)
    res = m._merge_dirs("Src", "Dest", {"ops": {}}, "op")
    return m, fd, res


def test_dirmerge_unique_descendant_is_server_side_moved(tmp_path, monkeypatch):
    m, fd, res = _merge(tmp_path, monkeypatch, {
        "Src": {"dir": True}, "Dest": {"dir": True},
        "Src/only-here.bin": {"dir": False, "size": 10, "md5": "a"},
    })
    assert res["moved"] == 1
    assert ("Src/only-here.bin", "Dest/only-here.bin") in fd.moves
    assert "Dest/only-here.bin" in fd.e


def test_dirmerge_identical_file_keeps_one_survivor(tmp_path, monkeypatch):
    m, fd, res = _merge(tmp_path, monkeypatch, {
        "Src": {"dir": True}, "Dest": {"dir": True},
        "Src/same.bin": {"dir": False, "size": 10, "md5": "aaa"},
        "Dest/same.bin": {"dir": False, "size": 10, "md5": "aaa"},
    })
    assert res["dupes"] == 1 and res["moved"] == 0
    assert fd.deletes == ["Src/same.bin"], "the source copy is removed, not moved"
    assert "Dest/same.bin" in fd.e, "the survivor must remain"


def test_dirmerge_differing_file_preserves_both(tmp_path, monkeypatch):
    m, fd, res = _merge(tmp_path, monkeypatch, {
        "Src": {"dir": True}, "Dest": {"dir": True},
        "Src/x.bin": {"dir": False, "size": 10, "md5": "aaa"},
        "Dest/x.bin": {"dir": False, "size": 99, "md5": "bbb"},
    })
    assert res["conflicts"] == 1 and not fd.deletes
    assert "Dest/x.bin" in fd.e, "the destination copy must survive untouched"
    kept = [p for p in fd.e if "__from_" in p]
    assert kept and "__src_aaa" in kept[0], "the source copy lands under provenance naming"


def test_dirmerge_unhashable_file_is_treated_as_differing_not_duplicate(
        tmp_path, monkeypatch):
    """No MD5 means no evidence. Deleting on absence of evidence is the wrong default."""
    m, fd, res = _merge(tmp_path, monkeypatch, {
        "Src": {"dir": True}, "Dest": {"dir": True},
        "Src/g.doc": {"dir": False, "size": 10, "md5": ""},
        "Dest/g.doc": {"dir": False, "size": 10, "md5": ""},
    })
    assert res["dupes"] == 0, "an unhashable pair must never be called a duplicate"
    assert res["conflicts"] == 1
    assert not fd.deletes


def test_dirmerge_recurses_into_nested_directory_collisions(tmp_path, monkeypatch):
    m, fd, res = _merge(tmp_path, monkeypatch, {
        "Src": {"dir": True}, "Dest": {"dir": True},
        "Src/a": {"dir": True}, "Dest/a": {"dir": True},
        "Src/a/b": {"dir": True}, "Dest/a/b": {"dir": True},
        "Src/a/b/deep-unique.bin": {"dir": False, "size": 4, "md5": "u"},
        "Src/a/b/deep-same.bin": {"dir": False, "size": 4, "md5": "s"},
        "Dest/a/b/deep-same.bin": {"dir": False, "size": 4, "md5": "s"},
    })
    assert res["recursed"] >= 2, "it must descend through both nested levels"
    assert "Dest/a/b/deep-unique.bin" in fd.e, "a deep unique file must arrive"
    assert fd.deletes == ["Src/a/b/deep-same.bin"], "the deep duplicate is de-duplicated"


def test_dirmerge_directory_versus_file_name_clash_preserves_both(tmp_path, monkeypatch):
    m, fd, res = _merge(tmp_path, monkeypatch, {
        "Src": {"dir": True}, "Dest": {"dir": True},
        "Src/thing": {"dir": True},
        "Src/thing/inner.bin": {"dir": False, "size": 1, "md5": "z"},
        "Dest/thing": {"dir": False, "size": 5, "md5": "y"},
    })
    assert res["conflicts"] == 1, "a directory and a file are not versions of each other"
    assert "Dest/thing" in fd.e and fd.e["Dest/thing"]["dir"] is False
    preserved = [p for p in fd.e if "__from_" in p]
    assert preserved, "the source directory must be preserved, not discarded"
    # Assert the BRANCH, not just the outcome. Without the type-mismatch guard the code
    # falls through to the both-files branch and happens to preserve it too, because a
    # directory exposes no MD5 -- same result, different reasoning, and a test that cannot
    # tell them apart is not testing the guard. The `dir` tag is produced only by the
    # type-mismatch branch.
    assert any("__src_dir" in p for p in preserved), (
        "the preserved copy must be tagged by the directory-vs-file branch; a size tag "
        "means the both-files branch handled it by accident")


def test_drive_children_routes_a_directory_collision_into_the_recursive_merge(
        tmp_path, monkeypatch):
    """The routing itself needs a test.

    Every other merge test calls _merge_dirs directly, so disabling the branch in
    do_drive_children that reaches it left all of them green while a directory collision
    fell back to a bare `moveto` -- the exact behaviour the merge policy forbids.
    """
    m = _load(tmp_path)
    fd = FakeDrive({
        "Bucket": {"dir": True}, "Dest": {"dir": True},
        "Bucket/coll": {"dir": True}, "Dest/coll": {"dir": True},
        "Bucket/coll/same.bin": {"dir": False, "size": 8, "md5": "q"},
        "Dest/coll/same.bin": {"dir": False, "size": 8, "md5": "q"},
        "Bucket/coll/new.bin": {"dir": False, "size": 8, "md5": "n"},
    })
    monkeypatch.setattr(m, "sh", fd.sh)
    st = {"ops": {}}
    m.do_drive_children({"id": "op", "src": "Bucket",
                         "classify": lambda n, d: "Dest", "why": "w"}, st, apply=True)

    assert ("Bucket/coll", "Dest/coll") not in fd.moves, (
        "a directory whose destination exists must NOT be moved wholesale onto it")
    assert "Dest/coll/new.bin" in fd.e, "the unique descendant must be merged in"
    assert fd.deletes == ["Bucket/coll/same.bin"], (
        "the identical descendant must be de-duplicated, keeping the destination survivor")
    assert "recursive merge" in st["ops"]["op::coll"]["detail"]


def test_dirmerge_removes_source_only_when_empty_and_destination_verifies(
        tmp_path, monkeypatch):
    m, fd, res = _merge(tmp_path, monkeypatch, {
        "Src": {"dir": True}, "Dest": {"dir": True},
        "Src/one.bin": {"dir": False, "size": 3, "md5": "m"},
    })
    assert "Src" in fd.rmdirs, "an emptied source container is removed"

    # And when the destination cannot be confirmed, the source container survives.
    m2 = _load(tmp_path / "second")
    fd2 = FakeDrive({"Src": {"dir": True}, "Dest": {"dir": True},
                     "Src/one.bin": {"dir": False, "size": 3, "md5": "m"}})
    real = fd2.sh

    def sh_hiding_dest(args, timeout=0):
        import subprocess
        if args[0] == "rclone" and args[1] == "lsjson" and args[2].endswith(":Dest") \
                and "--stat" not in args:
            return subprocess.CompletedProcess(args, 1, "", "vanished")
        return real(args, timeout)

    monkeypatch.setattr(m2, "sh", sh_hiding_dest)
    r2 = m2._merge_dirs("Src", "Dest", {"ops": {}}, "op")
    assert "Src" not in fd2.rmdirs, "source must survive when the destination cannot verify"
    assert r2["failed"] >= 1


def test_dirmerge_depth_limit_stops_runaway_recursion(tmp_path, monkeypatch):
    m = _load(tmp_path)
    entries = {"Src": {"dir": True}, "Dest": {"dir": True}}
    sp, dp = "Src", "Dest"
    for _ in range(m.MERGE_MAX_DEPTH + 5):
        sp, dp = sp + "/d", dp + "/d"
        entries[sp] = {"dir": True}
        entries[dp] = {"dir": True}
    fd = FakeDrive(entries)
    monkeypatch.setattr(m, "sh", fd.sh)
    res = m._merge_dirs("Src", "Dest", {"ops": {}}, "op")
    assert res["recursed"] <= m.MERGE_MAX_DEPTH + 1
    assert res["failed"] >= 1, "hitting the limit is reported, not silently ignored"
