"""The record of licences that have actually cleared. This is what earns `ready`.

`gateway.unit_state` may only report `ready` once a licence has cleared end to end at least
once — condition 5 of the five in `docs/specs/gateway-completion.md` §4. That condition needs
somewhere to be recorded, and the recording has to be *evidence*, not a setting: an operator
who can turn the light green by editing a config file has a decorative indicator, which
`.claude/CLAUDE.md` forbids outright.

So a clearance is only ever appended by the code path that verified a real settlement, and it
carries the nonce, block and transaction it came from. Anyone can check the claim against the
chain afterwards, which is the property that makes the green light honest.

## Where this lives, and why not `run/`

`run/` is the GPU mutex, pidfiles and logs — state that is *meant* to be disposable and that
`.claude/CLAUDE.md` warns will eventually be logrotated or cleared. A cleared licence is a
financial record; losing it silently downgrades the rack from `ready` to `offline` with no
explanation. It goes under `backend/state/` instead, beside the other durable API output.

## Append-only, and tolerant of a corrupt line

One clearance per line, JSON. A truncated final line — a power cut mid-write — must not make
the whole file unreadable, so parsing skips lines it cannot read rather than raising. It
counts them, and `unit_state` can say so, because silently discarding financial records is
its own kind of dishonesty.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

# backend/gateway/store.py -> backend/
_BACKEND = Path(__file__).resolve().parent.parent.parent
DEFAULT_PATH = _BACKEND / "state" / "clearances.jsonl"


@dataclass(frozen=True)
class Clearance:
    """One licence that settled, with enough to re-check it against the chain."""
    nonce: int
    payer: str
    token: str
    amount: int
    workspace: str
    network: str
    contract: str
    at_block: int
    at_time: int
    recorded_at: float = field(default_factory=time.time)


class ClearanceStore:
    """Append-only clearances. Never raises on read; a missing file is simply zero of them."""

    def __init__(self, path: str | os.PathLike | None = None) -> None:
        self.path = Path(path) if path is not None else DEFAULT_PATH
        self.bad_lines = 0

    # ------------------------------------------------------------------------------ writing

    def append(self, c: Clearance) -> None:
        """Record a clearance durably. Creates the directory on first use.

        Written with a flush and an fsync because the value of this file is precisely that it
        survives the crash that happens ten seconds later.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(asdict(c), sort_keys=True, separators=(",", ":")) + "\n"
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())

    # ------------------------------------------------------------------------------ reading

    def all(self) -> list[Clearance]:
        """Every clearance on disk, oldest first. Unreadable lines are skipped and counted."""
        self.bad_lines = 0
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        except OSError:
            # Unreadable store is zero clearances, which reads as `offline`. Fail closed.
            self.bad_lines = -1
            return []
        out: list[Clearance] = []
        for line in raw.splitlines():
            if not line.strip():
                continue
            try:
                out.append(Clearance(**json.loads(line)))
            except (ValueError, TypeError):
                self.bad_lines += 1
        return out

    def count(self) -> int:
        return len(self.all())

    def latest(self, network: str | None = None, contract: str | None = None) -> Clearance | None:
        """The most recent clearance, optionally only for one network and contract.

        `unit_state` filters on both: a licence that cleared on Nile is not evidence that the
        mainnet surface works, and a licence against a contract that has since been redeployed
        is evidence about an address nobody is pointed at any more.
        """
        best: Clearance | None = None
        for c in self.all():
            if network is not None and c.network != network:
                continue
            if contract is not None and c.contract != contract:
                continue
            if best is None or c.at_time > best.at_time:
                best = c
        return best

    def has_cleared(self, network: str, contract: str) -> bool:
        return self.latest(network, contract) is not None
