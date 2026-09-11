"""Job store: live jobs in memory, terminal jobs journaled to disk.

Active jobs still die with the process (an in-flight job at crash time never
reaches its terminal state, so it never reaches the journal). But every job
that FINISHES — done or failed — is appended to .run/jobs.jsonl, so polling
a finished job keeps answering across restarts and /jobs can list history."""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

TERMINAL_STATES = {"done", "failed"}
# queued -> generating -> resolving -> creating -> done | failed


@dataclass
class Job:
    id: str
    user: str
    prompt: str
    track_count: int
    name: str | None
    public: bool
    use_taste_profile: bool
    blend_with: list = field(default_factory=list)
    blend_skipped: list = field(default_factory=list)  # [{user, reason}] — never fails the job
    state: str = "queued"
    progress: str = ""
    error: str | None = None
    raw_llm_output: str | None = None  # saved when the model's JSON never parsed
    playlist_id: str | None = None
    playlist_url: str | None = None
    tracks_added: int = 0
    tracks_dropped: list = field(default_factory=list)
    cover: str = ""  # "ok" | "skipped: <why>" — cover art never fails a job
    charged: int = 0  # SyMoN tokens actually charged (0 for owner/free)
    task: asyncio.Task | None = None

    def fail(self, message: str) -> None:
        """Idempotent: the first failure reason wins, done is never demoted."""
        if self.state not in TERMINAL_STATES:
            self.state = "failed"
            self.error = message

    def as_dict(self) -> dict:
        out = {
            "job_id": self.id,
            "user": self.user,
            "state": self.state,
            "progress": self.progress,
        }
        if self.state == "failed":
            out["error"] = self.error or "unknown"
            if self.raw_llm_output is not None:
                out["raw_llm_output"] = self.raw_llm_output
        if self.state == "done":
            out.update(
                playlist_id=self.playlist_id,
                playlist_url=self.playlist_url,
                tracks_added=self.tracks_added,
                tracks_dropped=self.tracks_dropped,
                cover=self.cover,
                charged=self.charged,
            )
            if self.blend_with:
                out["blend_with"] = self.blend_with
                out["blend_skipped"] = self.blend_skipped
        return out


class JobStore:
    def __init__(self):
        self._jobs: dict[str, Job] = {}

    def create(
        self,
        user: str,
        prompt: str,
        track_count: int,
        name: str | None,
        public: bool,
        use_taste_profile: bool,
        blend_with: list | None = None,
    ) -> Job:
        job = Job(
            id=uuid.uuid4().hex[:12],
            user=user,
            prompt=prompt,
            track_count=track_count,
            name=name,
            public=public,
            use_taste_profile=use_taste_profile,
            blend_with=blend_with or [],
        )
        self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def all(self) -> list[Job]:
        return list(self._jobs.values())


class JobJournal:
    """Append-only JSONL of terminal job states. Small, scanned on read."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def append(self, job: Job) -> None:
        record = job.as_dict()
        record["prompt"] = job.prompt
        record["finished_at"] = time.time()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._restrict()

    def _restrict(self) -> None:
        """0600. This file is the cross-tenant boundary written to disk.

        /jobs and /playlist/{id} filter by _visible_users() so one member cannot
        read another's prompts, playlist URLs or charges. The journal those
        routes read from was mode 0664 — so the boundary held at the route and
        not on the filesystem, and any local account could read every member's
        record straight out of it. Found 2026-08-11.

        Non-fatal: a journal we cannot chmod is still one we must be able to
        append to, and failing a finished job over a permissions edge case
        would lose the record entirely.
        """
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def _records(self) -> list[dict]:
        try:
            lines = self.path.read_text().strip().split("\n")
        except FileNotFoundError:
            return []
        records = []
        for line in lines:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue  # a torn write must not poison the whole journal
            if isinstance(record, dict) and record.get("job_id"):
                records.append(record)
        return records

    def lookup(self, job_id: str) -> dict | None:
        for record in reversed(self._records()):  # last write wins
            if record["job_id"] == job_id:
                return record
        return None

    def recent(self, n: int = 20) -> list[dict]:
        return list(reversed(self._records()))[:n]
