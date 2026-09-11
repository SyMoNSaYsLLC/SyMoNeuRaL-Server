"""SyMoNeuRaL Local Model Overclocking — GPU / CPU / RAM budgets for this box.

Named by the owner, 2026-09-11: *"lets call it symoneural local model overclocking"*.

The ask it answers, same day: *"i need to be able to control my gpu ram cpu % to test. example
100% gpu 100% cpu %100 ram or 50 50 50 or 10 80 10. these % will need to be maxed based off
your professional opinion but i want to be able to go MAX PERFORMANCE + 5%"*.

## "MAX PERFORMANCE + 5%" is real on this card, and it is not a figure of speech

Measured 2026-09-11 with `nvidia-smi --query-gpu=power.default_limit,power.min_limit,power.max_limit`:

    power.min_limit      250 W
    power.default_limit  300 W     <- where the card sits now
    power.max_limit      330 W     <- the firmware ceiling, exactly +10%

So **+5% is 315 W and it is settable**, and +10% (330 W) is the hard stop the firmware
enforces. Above that there is nothing to give: 330 W is not a policy this module is choosing
to apply, it is the number the card reports as its own maximum. `plan()` caps there and says
so rather than accepting 140% and quietly clamping — a control that silently ignores its
input is the failure mode this repo keeps finding.

**This is the real meaning of "overclocking" here, and it is worth being precise about it:**
this raises the *power envelope*, which lets the card hold its boost clocks longer under
sustained load. It does not raise the clock ceiling itself (`clocks.max.sm` is 3210 MHz and is
firmware's) and it does not alter voltage curves. What you get is less throttling, not a
higher top speed — which on a sustained inference workload is usually the number that matters.

## The distinction that makes these percentages meaningful

**A cap is not a load.** Setting "GPU 100%" does not make the GPU busy; it removes the limit
that would stop it from getting busy. Making it *reach* 100% requires a workload. Both halves
are published separately, because a dashboard with one slider labelled "GPU %" that means
sometimes one and sometimes the other is unusable for the thing it is for — testing.

* `plan()` computes **caps**: the ceilings a workload will be held under.
* Reaching a target utilisation is a **load** question, and this box already has real ones —
  `performance/benchmarks/`, the model itself. Nothing here generates synthetic load, because
  a synthetic number is not the thing being tested.

## What needs root, stated rather than discovered

Measured on this host, not assumed:

| control | mechanism | root? |
|---|---|---|
| GPU power limit | `nvidia-smi -pl <W>` | **yes** — verified: "Insufficient Permissions" |
| CPU quota | systemd `CPUQuota=` | **yes** — `/sys/fs/cgroup` is not writable by this user |
| RAM cap | systemd `MemoryMax=` | **yes** — same |
| VRAM budget | engine args + governor floors | **no** — ours already |

So `plan()` **computes and returns exact commands and never runs them.** A web route that
shells out to `sudo` is a privilege-escalation surface reachable from a browser, and this box
already decided that surfaces are guarded by unreachability rather than by secrets — which
only holds while the surfaces cannot escalate. The owner runs the printed commands, or
authorises a single helper, and that is a decision to take deliberately rather than by
dragging a slider.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
from typing import Any

#: Read once at import from the card itself; `None` if nvidia-smi could not answer.
#: Never a hardcoded 300/330 -- those are this card's numbers, not every card's.
_POWER_FIELDS = ("power.min_limit", "power.default_limit", "power.max_limit")

#: The floor the repo learned the hard way. `registry.py`: "~14.2 GiB is what is free in
#: practice on a 15.92 GiB card. Budgeting against the nameplate is how a run OOMs at step 0."
PRACTICAL_VRAM_FRACTION = 14.2 / 15.92

#: systemd unit the CPU/RAM caps would apply to.
UNIT = "symoneural-api.service"


def _smi(fields: tuple[str, ...]) -> dict[str, float] | None:
    try:
        p = subprocess.run(
            ["nvidia-smi", f"--query-gpu={','.join(fields)}",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode != 0:
        return None
    cells = [c.strip() for c in p.stdout.strip().splitlines()[0].split(",")]
    try:
        return {f: float(c) for f, c in zip(fields, cells)}
    except ValueError:
        return None


def power_envelope() -> dict[str, Any]:
    """The card's own power bounds, read from the card. The basis for "+5%"."""
    vals = _smi(_POWER_FIELDS)
    src = f"nvidia-smi --query-gpu={','.join(_POWER_FIELDS)}"
    if not vals:
        return {"available": False, "source": f"{src} did not answer"}
    default, top = vals["power.default_limit"], vals["power.max_limit"]
    return {
        "available": True,
        "min_w": vals["power.min_limit"],
        "default_w": default,
        "max_w": top,
        # The honest headline. Computed from two readings, both named.
        "headroom_pct": round(100 * (top - default) / default, 1),
        "source": src,
        "note": (f"the card permits {top:.0f} W against a {default:.0f} W default — "
                 f"'max performance +5%' is {default * 1.05:.0f} W and is real; "
                 f"+{100 * (top - default) / default:.0f}% is the firmware ceiling, "
                 f"and there is nothing above it to ask for."),
    }


def vram_envelope() -> dict[str, Any]:
    """Total VRAM, and the practical budget the repo's own runs established."""
    vals = _smi(("memory.total",))
    if not vals:
        return {"available": False, "source": "nvidia-smi --query-gpu=memory.total failed"}
    total = vals["memory.total"]
    return {
        "available": True,
        "total_mib": int(total),
        "practical_mib": int(total * PRACTICAL_VRAM_FRACTION),
        "source": "nvidia-smi --query-gpu=memory.total",
        "note": ("the practical figure is the nameplate scaled by the 14.2/15.92 ratio that "
                 "docs/specs/qlora-27b-measured.md and registry.py both record. Budgeting "
                 "against the nameplate is how a run OOMs at step 0 — 100% here means the "
                 "practical budget, and going above it is what 'over' is for."),
    }


def cpu_envelope() -> dict[str, Any]:
    threads = os.cpu_count() or 1
    return {
        "available": True,
        "threads": threads,
        "source": "os.cpu_count()",
        "note": (f"100% is all {threads} threads. systemd expresses this as "
                 f"CPUQuota={threads * 100}%, which is not a typo — the quota is per-core."),
    }


def ram_envelope() -> dict[str, Any]:
    try:
        for line in pathlib.Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                kb = int(line.split()[1])
                return {"available": True, "total_gib": round(kb / 1048576, 1),
                        "source": "/proc/meminfo MemTotal"}
    except (OSError, ValueError, IndexError):
        pass
    return {"available": False, "source": "/proc/meminfo unreadable"}


def envelopes() -> dict[str, Any]:
    """Every bound this box will honour, all read from the box."""
    return {"power": power_envelope(), "vram": vram_envelope(),
            "cpu": cpu_envelope(), "ram": ram_envelope()}


def _clamp(pct: float, ceiling: float) -> tuple[float, str | None]:
    """Clamp with a REASON, never silently. See the module docstring."""
    if pct < 0:
        return 0.0, "below 0% is not a budget; clamped to 0"
    if pct > ceiling:
        return ceiling, (f"asked for {pct:g}%, capped at {ceiling:g}% — that is the hardware "
                         f"ceiling read from this box, not a policy choice")
    return pct, None


def plan(gpu_pct: float, cpu_pct: float, ram_pct: float) -> dict[str, Any]:
    """Three percentages in, the real limits and the exact commands out. Runs nothing.

    100% means the practical maximum for each resource; above 100% is the hardware headroom
    where it exists, and is refused with a reason where it does not.
    """
    env = envelopes()
    out: dict[str, Any] = {"requested": {"gpu_pct": gpu_pct, "cpu_pct": cpu_pct,
                                         "ram_pct": ram_pct},
                           "envelopes": env, "commands": [], "clamps": [], "applied": False}

    # ---- GPU: percentage maps to the power limit, because that is what is settable ------
    p = env["power"]
    if p.get("available"):
        ceiling = 100 * p["max_w"] / p["default_w"]
        eff, why = _clamp(gpu_pct, ceiling)
        if why:
            out["clamps"].append({"resource": "gpu", "why": why})
        watts = round(p["default_w"] * eff / 100)
        watts = max(p["min_w"], min(p["max_w"], watts))
        out["gpu"] = {"power_w": watts, "of_default_pct": round(100 * watts / p["default_w"], 1),
                      "is_over_default": watts > p["default_w"]}
        out["commands"].append({
            "resource": "gpu", "needs_root": True,
            "command": f"sudo nvidia-smi -pl {watts:.0f}",
            "what": f"sets the board power limit to {watts:.0f} W",
            "undo": f"sudo nvidia-smi -pl {p['default_w']:.0f}"})

    v = env["vram"]
    if v.get("available"):
        eff, why = _clamp(gpu_pct, 100 * v["total_mib"] / v["practical_mib"])
        if why:
            out["clamps"].append({"resource": "vram", "why": why})
        out["vram"] = {"budget_mib": int(v["practical_mib"] * eff / 100),
                       "over_practical": eff > 100}

    # ---- CPU: a systemd quota, per-core ---------------------------------------------
    c = env["cpu"]
    eff, why = _clamp(cpu_pct, 100)       # no headroom above every core; say so
    if why:
        out["clamps"].append({"resource": "cpu",
                              "why": "there is no CPU above 100% of every core — "
                                     "clamped. Clock behaviour is the firmware's, not ours."})
    quota = round(c["threads"] * eff)
    out["cpu"] = {"quota_pct": quota, "threads_equivalent": round(c["threads"] * eff / 100, 2)}
    out["commands"].append({
        "resource": "cpu", "needs_root": True,
        "command": f"sudo systemctl set-property {UNIT} CPUQuota={quota}%",
        "what": f"caps {UNIT} at {eff:g}% of {c['threads']} threads",
        "undo": f"sudo systemctl set-property {UNIT} CPUQuota="})

    # ---- RAM: a systemd cap -----------------------------------------------------------
    r = env["ram"]
    if r.get("available"):
        eff, why = _clamp(ram_pct, 100)
        if why:
            out["clamps"].append({"resource": "ram",
                                  "why": "there is no RAM above what is installed."})
        gib = round(r["total_gib"] * eff / 100, 1)
        out["ram"] = {"cap_gib": gib}
        out["commands"].append({
            "resource": "ram", "needs_root": True,
            "command": f"sudo systemctl set-property {UNIT} MemoryMax={gib}G",
            "what": f"caps {UNIT} at {gib} GiB",
            "undo": f"sudo systemctl set-property {UNIT} MemoryMax="})

    out["note"] = ("computed, not applied. Every command above needs root, verified on this "
                   "host: nvidia-smi -pl answers 'Insufficient Permissions' and "
                   "/sys/fs/cgroup is not writable by this user. A web route that runs sudo "
                   "is a privilege-escalation surface reachable from a browser.")
    out["caps_are_not_load"] = ("these are ceilings. Reaching 100% utilisation needs a "
                                "workload — performance/benchmarks/ or the model itself.")
    return out


#: The three the owner named, plus the one this module exists to make honest.
PRESETS = [
    {"name": "balanced", "gpu": 50, "cpu": 50, "ram": 50},
    {"name": "cpu-heavy", "gpu": 10, "cpu": 80, "ram": 10},
    {"name": "everything", "gpu": 100, "cpu": 100, "ram": 100},
    {"name": "max performance +5%", "gpu": 105, "cpu": 100, "ram": 100,
     "what": "315 W on this card. Real, and above the 300 W default."},
    {"name": "max performance +10% (ceiling)", "gpu": 110, "cpu": 100, "ram": 100,
     "what": "330 W — the firmware maximum. Nothing above this exists to ask for."},
]
