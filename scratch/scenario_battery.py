"""
scenario_battery.py
===================
Ground-truth RCA scenario battery for ARVIS. Runs a fixed set of known-answer
fault cases (plus a normal negative-control) through the real swarm and scores
each on grounding + diagnosis quality. Prints an aggregate **contradiction rate**
(H4 faithfulness failures / syntheses) — the metric to watch before/after the
claim-first synthesis change.

Why this exists: we had been validating on a single scenario (AHU-07). Any change
to the synthesis/grounding stage must be measured across diverse faults — and
against a negative control that must NOT invent a fault out of normal telemetry.

Run:  /c/ProgramData/anaconda3/python scratch/scenario_battery.py
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
try:
    import dotenv
    dotenv.load_dotenv(str(ROOT / ".env"))
except Exception:
    pass

_TS = datetime.now().strftime("%Y%m%d_%H%M%S")
_RUN_DIR = ROOT / "runs" / f"battery_{_TS}"
_RUN_DIR.mkdir(parents=True, exist_ok=True)
os.environ["ARVIS_DB_PATH"] = str((_RUN_DIR / "battery.db").resolve())
os.environ["ARVIS_MEMORY_DIR"] = str((_RUN_DIR / "memories").resolve())
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")


# ── H4 contradiction counter (attaches to the queen logger) ─────────────────
class _ContradictionCounter(logging.Handler):
    _FAIL_RE = re.compile(r"Faithfulness FAILED\s+—\s+(\d+)\s+contradiction", re.IGNORECASE)

    def __init__(self):
        super().__init__()
        self.reset()

    def reset(self):
        self.syntheses = 0
        self.h4_failures = 0
        self.contradictions = 0
        self.claimbind_flags = 0
        self.numeric_stripped = 0

    def emit(self, record):
        try:
            msg = record.getMessage()
        except Exception:
            return
        if "── Synthesis START" in msg:
            self.syntheses += 1
        m = self._FAIL_RE.search(msg)
        if m:
            self.h4_failures += 1
            self.contradictions += int(m.group(1))
        if "[Queen][ClaimBind] flagged" in msg:
            _m = re.search(r"flagged\s+(\d+)", msg)
            if _m:
                self.claimbind_flags += int(_m.group(1))
        if "[NumericAudit] STRIPPED" in msg:
            _m = re.search(r"STRIPPED\s+(\d+)", msg)
            if _m:
                self.numeric_stripped += int(_m.group(1))


# ── Scenario definitions ────────────────────────────────────────────────────
# Each: equipment to register, baseline (for z-score history), fault points,
# alarms (SYMPTOMS only — no root cause named, no answer leak), the operator
# query, and loose expectations (keyword-based, not brittle).
SCENARIOS = [
    {
        "id": "ahu_oa_damper_slip",
        "equipment": ("AHU-07", "AHU Floor 28", "AHU", "Floor 28"),
        "baseline": [("MAT", "Mixed Air Temp", 24.0, "C", 35)],
        "points": [
            ("MAT", "Mixed Air Temp", 30.8, "C"),
            ("SAT", "Supply Air Temp", 16.5, "C"),
            ("OAT", "Outdoor Air Temp", 42.0, "C"),
            ("RAT", "Return Air Temp", 24.0, "C"),
            ("OA_DMPR", "OA Damper Position", 0.15, "fraction"),   # feedback lies (matches cmd)
            ("OA_DMPR_CMD", "OA Damper Command", 0.15, "fraction"),
            ("CHW_VALVE", "CHW Valve", 0.99, "fraction"),
        ],
        "alarms": [
            ("ALM-A07-1", "SAT", "Supply air 16.5C vs 13.5C setpoint — cannot hold supply temp", "CRITICAL"),
            ("ALM-A07-2", "MAT", "Mixed air temp 30.8C — high, z-score elevated", "HIGH"),
            ("ALM-A07-3", "CHW_VALVE", "CHW valve 99% — cooling capacity exhausted", "HIGH"),
        ],
        "query": "AHU-07 supply air is running hot and Floor 28 tenants are complaining. Walk me through what's driving it and the downstream impact.",
        "expect": {"fault": True, "min_hyps": 2, "grounded": True,
                   "leading_any": ["damper", "outdoor air", "oa", "mixing", "ventilation"]},
    },
    {
        "id": "coil_capacity_limit",
        "equipment": ("AHU-12", "AHU Floor 14", "AHU", "Floor 14"),
        "baseline": [("MAT", "Mixed Air Temp", 26.0, "C", 35)],
        "points": [
            # MAT consistent with 15% OA (no excess-OA signal) — forces coil-side reasoning
            ("MAT", "Mixed Air Temp", 26.7, "C"),
            ("SAT", "Supply Air Temp", 17.0, "C"),
            ("OAT", "Outdoor Air Temp", 42.0, "C"),
            ("RAT", "Return Air Temp", 24.0, "C"),
            ("OA_DMPR", "OA Damper Position", 0.15, "fraction"),
            ("OA_DMPR_CMD", "OA Damper Command", 0.15, "fraction"),
            ("CHW_VALVE", "CHW Valve", 0.99, "fraction"),
        ],
        "alarms": [
            ("ALM-A12-1", "SAT", "Supply air 17.0C vs 13.5C setpoint — cannot hold supply temp", "CRITICAL"),
            ("ALM-A12-2", "CHW_VALVE", "CHW valve 99% — at maximum cooling demand", "HIGH"),
        ],
        "query": "AHU-12 cannot hold supply air temperature even with the chilled-water valve wide open. What is the most likely cause?",
        "expect": {"fault": True, "min_hyps": 2, "grounded": True,
                   "leading_any": ["coil", "chilled water", "chw", "flow", "capacity", "heat transfer"]},
    },
    {
        "id": "chiller_low_efficiency",
        "equipment": ("CHILLER-01", "Chiller 1", "CHILLER", "Basement Plant"),
        "baseline": [("COP", "COP", 5.8, "", 35)],
        "points": [
            ("COP", "COP", 3.1, ""),
            ("KW", "Power", 420.0, "kW"),
            ("CHWS", "CHW Supply Temp", 7.2, "C"),
            ("CHWR", "CHW Return Temp", 13.8, "C"),
            ("COND_APPROACH", "Condenser Approach", 4.8, "C"),
        ],
        "alarms": [
            ("ALM-C01-1", "COP", "Chiller COP 3.1 — well below 5.8 baseline", "CRITICAL"),
            ("ALM-C01-2", "COND_APPROACH", "Condenser approach 4.8C — elevated", "HIGH"),
        ],
        "query": "Chiller-01 efficiency has dropped sharply. What is driving the COP loss?",
        "expect": {"fault": True, "min_hyps": 2, "grounded": True,
                   "leading_any": ["condenser", "approach", "fouling", "refrigerant", "efficiency", "cop"]},
    },
    {
        "id": "normal_negative_control",
        "equipment": ("AHU-21", "AHU Floor 5", "AHU", "Floor 5"),
        "baseline": [("MAT", "Mixed Air Temp", 24.0, "C", 35)],
        "points": [
            ("MAT", "Mixed Air Temp", 24.1, "C"),
            ("SAT", "Supply Air Temp", 13.4, "C"),     # holding setpoint
            ("OAT", "Outdoor Air Temp", 41.0, "C"),
            ("RAT", "Return Air Temp", 24.0, "C"),
            ("OA_DMPR", "OA Damper Position", 0.15, "fraction"),
            ("OA_DMPR_CMD", "OA Damper Command", 0.15, "fraction"),
            ("CHW_VALVE", "CHW Valve", 0.55, "fraction"),
        ],
        "alarms": [],  # NO alarms — must not invent a fault
        "query": "Is AHU-21 operating normally, or is there a developing problem?",
        "expect": {"fault": False, "min_hyps": 0, "grounded": True, "leading_any": []},
    },
]


def _hdr(t):
    print(f"\n{'─'*72}\n  {t}\n{'─'*72}")


async def run_scenario(scen, counter, idx):
    # ── Per-scenario ISOLATION: fresh engine + fresh DB/memory dir ──────────
    # Without this, injected points/alarms/beliefs/skillbook/turn-ledger from a
    # prior scenario bleed into the next (every scenario inherited AHU-07's
    # damper story). Each scenario gets its own clean ARVIS instance, on its own
    # API port (each start() boots uvicorn — reusing :8000 collides).
    _sdir = _RUN_DIR / scen["id"]
    _sdir.mkdir(parents=True, exist_ok=True)
    os.environ["ARVIS_DB_PATH"] = str((_sdir / "bms.db").resolve())
    os.environ["ARVIS_MEMORY_DIR"] = str((_sdir / "memories").resolve())
    # Eval isolation: don't let scenario N's skill auto-write pollute the shared
    # knowledge_base that scenario N+1 recalls from in the same battery run.
    os.environ["ARVIS_DISABLE_SKILL_WRITE"] = "1"

    from agent_commercial.main import OpsCopilot
    copilot = OpsCopilot(mode="simulator", api_port=8050 + idx)
    await copilot.start()
    bms_state = copilot.state_engine
    llm_agent = copilot.llm_agent
    # Silence the B9 autonomous dispatcher so the eval measures exactly ONE
    # investigation per scenario (no concurrent self-triggered swarms).
    try:
        copilot._dispatcher = None
    except Exception:
        pass

    from agent_commercial.bms_data_model import (
        BMSDataPoint, Alarm, AlarmSeverity, AlarmState, Equipment, EquipmentType, EquipmentStatus,
    )
    eq_id, eq_name, eq_type, eq_loc = scen["equipment"]
    _sev = {"CRITICAL": AlarmSeverity.CRITICAL, "HIGH": AlarmSeverity.HIGH, "MEDIUM": AlarmSeverity.MEDIUM}
    try:
        await bms_state.register_equipment(Equipment(
            equipment_id=eq_id, name=eq_name,
            equipment_type=getattr(EquipmentType, eq_type, EquipmentType.AHU),
            location=eq_loc, status=EquipmentStatus.RUNNING,
        ))
    except Exception as e:
        print(f"    register {eq_id} failed: {e}")

    async def inject(pid, name, val, unit):
        try:
            await bms_state.update_point(BMSDataPoint(
                point_id=f"{eq_id}/{pid}", equipment_id=eq_id, name=name,
                value=val, unit=unit, timestamp=datetime.now(), source="simulator",
            ))
        except Exception as e:
            print(f"    inject {pid} failed: {e}")

    import random as _rnd
    for pid, name, mean, unit, n in scen.get("baseline", []):
        for _ in range(n):
            await inject(pid, name, round(mean + _rnd.uniform(-0.4, 0.4), 2), unit)
    for pid, name, val, unit in scen["points"]:
        await inject(pid, name, val, unit)
    for aid, src, msg, sev in scen.get("alarms", []):
        try:
            await bms_state.add_alarm(Alarm(
                alarm_id=aid, source_point_id=f"{eq_id}/{src}", equipment_id=eq_id,
                message=msg, severity=_sev[sev], state=AlarmState.ACTIVE,
                triggered_at=datetime.now(),
            ))
        except Exception as e:
            print(f"    alarm {aid} failed: {e}")

    snap = await bms_state.get_snapshot()
    ctx = {"source": "battery", "LIVE_BMS_SNAPSHOT": snap}
    counter.reset()
    t0 = datetime.now()
    resp = await llm_agent.chat(query=scen["query"], context=ctx, channel="demo")
    elapsed = (datetime.now() - t0).total_seconds()
    ir = getattr(resp, "investigation_result", None) or {}

    rc = ir.get("root_cause", {}) or {}
    hyps = ir.get("hypotheses") or []
    leading = (hyps[0].get("label", "") if hyps else (rc.get("statement") or "")).lower()
    grounded = bool(ir.get("fully_grounded"))
    confirmed = bool(rc.get("confirmed"))
    exp = scen["expect"]

    # ── scoring ──
    checks = []
    if exp["fault"]:
        checks.append(("grounded", grounded == exp["grounded"]))
        checks.append((f">= {exp['min_hyps']} hypotheses", len(hyps) >= exp["min_hyps"]))
        checks.append(("leading matches expected class",
                       any(k in leading for k in exp["leading_any"]) if exp["leading_any"] else True))
        checks.append(("no unverified in confirmed", (not confirmed) or (not ir.get("has_unverified_claims"))))
    else:
        # negative control: must NOT confirm a fabricated fault
        checks.append(("did NOT confirm a fault", not confirmed))
        checks.append(("grounded (no fabricated claims)", grounded or ir.get("abstained")))

    passed = sum(1 for _, ok in checks if ok)
    print(f"\n  ▶ {scen['id']}  ({elapsed:.0f}s)")
    print(f"    leading: {leading[:70] or '—'}")
    print(f"    grounded={grounded} confirmed={confirmed} hyps={len(hyps)} "
          f"dominance={(ir.get('differential') or {}).get('dominance')} "
          f"h4_fails={counter.h4_failures} contradictions={counter.contradictions}")
    for name, ok in checks:
        print(f"      {'✅' if ok else '❌'} {name}")
    result = {
        "id": scen["id"], "passed": passed, "total": len(checks),
        "h4_failures": counter.h4_failures, "contradictions": counter.contradictions,
        "claimbind": counter.claimbind_flags, "numeric_stripped": counter.numeric_stripped,
        "syntheses": max(counter.syntheses, 1), "elapsed": elapsed,
        "grounded": grounded, "confirmed": confirmed, "hyps": len(hyps),
        "leading": leading[:70],
    }
    try:
        await copilot.stop()
    except Exception:
        pass
    return result


async def _run_one(scenario_id: str, out_path: str):
    """Single-scenario entry — runs in its OWN process (fresh module singletons,
    so no cross-investigation recall bleed). Writes result JSON to out_path."""
    import json as _json
    scen = next((s for s in SCENARIOS if s["id"] == scenario_id), None)
    idx = [s["id"] for s in SCENARIOS].index(scenario_id) if scen else 0
    counter = _ContradictionCounter()
    logging.getLogger("arvis.swarm.queen").addHandler(counter)
    try:
        result = await run_scenario(scen, counter, idx)
    except Exception as e:
        import traceback; traceback.print_exc()
        result = {"id": scenario_id, "passed": 0, "total": 1, "error": str(e),
                  "h4_failures": 0, "contradictions": 0, "claimbind": 0,
                  "numeric_stripped": 0, "syntheses": 1, "elapsed": 0,
                  "grounded": False, "confirmed": False, "hyps": 0, "leading": ""}
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            _json.dump(result, f)
    except Exception as _w:
        print(f"  result write failed: {_w}")
    print(f"  ✔ scenario done, result written. Forcing exit.")
    sys.stdout.flush()
    # Engine leaves uvicorn + apscheduler threads alive; normal return hangs.
    # Hard-exit so the parent's subprocess call returns.
    os._exit(0)


def main():
    """Orchestrator — spawns each scenario in a SEPARATE process for true
    isolation (ARVIS memory stores are module-level singletons; only a fresh
    process guarantees no recall bleed between scenarios)."""
    import json as _json
    import subprocess

    results = []
    for scen in SCENARIOS:
        sid = scen["id"]
        out_path = str((_RUN_DIR / f"{sid}.result.json").resolve())
        print(f"\n{'='*72}\n  RUNNING (isolated process): {sid}\n{'='*72}", flush=True)
        try:
            # No capture → child output streams live (so it never LOOKS frozen).
            subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--run", sid, "--out", out_path],
                env={**os.environ}, timeout=600,
            )
        except subprocess.TimeoutExpired:
            print(f"  ⏱ {sid} timed out (600s)")
        res = None
        try:
            with open(out_path, "r", encoding="utf-8") as f:
                res = _json.load(f)
        except Exception:
            pass
        if res is None:
            res = {"id": sid, "passed": 0, "total": 1, "h4_failures": 0, "contradictions": 0,
                   "claimbind": 0, "numeric_stripped": 0, "syntheses": 1, "elapsed": 0,
                   "grounded": False, "confirmed": False, "hyps": 0, "leading": "(no result)"}
        results.append(res)

    # ── Aggregate scorecard ──
    _hdr("BATTERY SCORECARD")
    tot_checks = sum(r["total"] for r in results)
    tot_pass = sum(r["passed"] for r in results)
    tot_synth = sum(r["syntheses"] for r in results)
    tot_contra = sum(r["contradictions"] for r in results)
    tot_h4fail = sum(r["h4_failures"] for r in results)
    print(f"  {'scenario':<26} {'pass':>6} {'grnd':>5} {'conf':>5} {'hyp':>4} {'h4f':>4} {'con':>4}  leading")
    for r in results:
        print(f"  {r['id']:<26} {str(r['passed'])+'/'+str(r['total']):>6} "
              f"{str(r['grounded']):>5} {str(r['confirmed']):>5} {r['hyps']:>4} "
              f"{r['h4_failures']:>4} {r['contradictions']:>4}  {r.get('leading','')[:36]}")
    print("─" * 72)
    print(f"  CHECKS PASSED          : {tot_pass}/{tot_checks}")
    print(f"  SYNTHESES              : {tot_synth}")
    print(f"  H4 FAILURES            : {tot_h4fail}")
    print(f"  TOTAL CONTRADICTIONS   : {tot_contra}")
    print(f"  CONTRADICTION RATE     : {tot_contra/tot_synth:.2f} per synthesis  ◀ watch before/after claim-first")
    print(f"  CLAIMBIND FLAGS        : {sum(r['claimbind'] for r in results)}")
    print(f"  NUMERIC STRIPPED       : {sum(r['numeric_stripped'] for r in results)}")
    print("═" * 72)
    return 0 if tot_pass == tot_checks else 1


if __name__ == "__main__":
    if "--run" in sys.argv:
        _sid = sys.argv[sys.argv.index("--run") + 1]
        _out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else "result.json"
        raise SystemExit(asyncio.run(_run_one(_sid, _out)))
    raise SystemExit(main())
