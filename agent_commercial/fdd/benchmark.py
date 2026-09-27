"""
FDD benchmark on public, labelled data — LBNL FDD Data Sets (DOI 10.25984/1881324).

Scores the ARVIS rule engine the way FDD evaluations usually do, per day:
  * fault-free year  → false-alarm rate  (share of running days with any confirmed fault)
  * each fault year  → detection rate    (share of running days with any confirmed fault)
  * which rules fired, per scenario      (does the right rule family catch the fault?)

The LBNL files are not bundled (≈0.6–1.1 GB each, free registration at
https://faultdetection.lbl.gov/data/). Download and unzip, then:

    python -m agent_commercial.fdd.benchmark --lbnl-sdahu <dir with *_annual.csv> \
        --out reports/fdd_benchmark_sdahu

Point mapping follows the dataset documentation (Table 2). Commands, not
positions, are mapped for valves and dampers — exactly what a BMS exposes and
what the LBNL leak/stuck faults corrupt (position ≠ command).
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd

from agent_commercial.fdd.engine import FDDEngine, enrich_context
from agent_commercial.fdd.finding import Outcome
from agent_commercial.fdd.frame import EquipmentFrame
from agent_commercial.semantics import PointRole as R, to_canonical

logger = logging.getLogger("arvis.fdd.benchmark")

# LBNL SDAHU column → (ARVIS role, unit as documented)
LBNL_SDAHU_MAP: Dict[str, Tuple[R, str]] = {
    "SA_TEMP": (R.SUPPLY_AIR_TEMP, "degF"),
    "SA_TEMPSPT": (R.SUPPLY_AIR_TEMP_SP, "degF"),
    "OA_TEMP": (R.OUTSIDE_AIR_TEMP, "degF"),
    "MA_TEMP": (R.MIXED_AIR_TEMP, "degF"),
    "RA_TEMP": (R.RETURN_AIR_TEMP, "degF"),
    "SF_SPD_DM": (R.SUPPLY_FAN_STATUS, ""),
    "SF_CS": (R.SUPPLY_FAN_SPEED, ""),
    "OA_DMPR_DM": (R.OUTSIDE_AIR_DAMPER, ""),
    "CHWC_VLV_DM": (R.COOLING_VALVE, ""),
    "SA_SP": (R.DUCT_STATIC_PRESSURE, "inH2O"),
    "SA_SPSPT": (R.DUCT_STATIC_PRESSURE_SP, "inH2O"),
    "SA_CFM": (R.SUPPLY_AIRFLOW, "cfm"),
    "OA_CFM": (R.OUTSIDE_AIRFLOW, "cfm"),
    "SF_WAT": (R.ELECTRIC_POWER, "W"),
    "SYS_CTL": (R.OCCUPANCY, ""),
}
ZONE_COL = re.compile(r"^ZONE_TEMP_(\d+)$")

# Ground truth from the dataset documentation (Table 4): scenario → fault class.
SDAHU_SCENARIOS = {
    "AHU_annual": "fault_free",
    "sa_bias": "sat_sensor_bias", "oa_bias": "oat_sensor_bias",
    "coi_leakage": "cooling_valve_leak", "coi_stuck": "cooling_valve_stuck",
    "damper_stuck": "oa_damper_stuck",
}


def scenario_of(name: str) -> str:
    for prefix, cls in SDAHU_SCENARIOS.items():
        if name.startswith(prefix):
            return cls
    return "unknown"


def _vector_canonical(s: pd.Series, unit: str, role: R) -> pd.Series:
    """Vectorised to_canonical. Linear units use the scalar conversion's slope and
    intercept; fraction/binary keep to_canonical's exact semantics."""
    from agent_commercial.semantics.point_roles import ROLE_QUANTITY, Quantity
    q = ROLE_QUANTITY[role]
    if q is Quantity.BINARY:
        return (s >= 0.5).astype(float).where(s.notna())
    if q is Quantity.FRACTION and unit in ("", "frac"):
        return s.where(s <= 1.0, s / 100.0)
    a, b = to_canonical(0.0, unit, role), to_canonical(1.0, unit, role)
    if a is None or b is None:
        raise ValueError(f"cannot convert unit {unit!r} for {role.value}")
    return s * (b - a) + a


def _timestamp_column(df: pd.DataFrame) -> str:
    for c in df.columns:
        if re.search(r"time|date", str(c), re.I):
            return c
    return df.columns[0]


def load_lbnl_sdahu(csv_path: Path, *, resample_seconds: int = 300) -> Dict[str, EquipmentFrame]:
    """One LBNL SDAHU year → {'AHU': frame, 'ZONE-1'…'ZONE-5': frames} in SI roles."""
    raw = pd.read_csv(csv_path)
    ts_col = _timestamp_column(raw)
    idx = pd.to_datetime(raw[ts_col], errors="coerce")
    raw = raw.loc[idx.notna()].set_index(idx[idx.notna()])
    freq = f"{int(resample_seconds)}s"

    def convert(col: str, role: R, unit: str) -> pd.Series:
        return _vector_canonical(pd.to_numeric(raw[col], errors="coerce"), unit, role).resample(freq).mean()

    ahu_cols = {role.value: convert(col, role, unit)
                for col, (role, unit) in LBNL_SDAHU_MAP.items() if col in raw.columns}
    ahu = pd.DataFrame(ahu_cols)
    frames = {"AHU": EquipmentFrame("AHU", "ahu", ahu,
                                    points_used={role.value: col for col, (role, _) in LBNL_SDAHU_MAP.items()
                                                 if col in raw.columns},
                                    role_sources={c: "explicit" for c in ahu.columns},
                                    design_attributes={"economizer": True, "has_vfd": True})}
    for col in raw.columns:
        m = ZONE_COL.match(str(col))
        if not m:
            continue
        zid = f"ZONE-{m.group(1)}"
        zdf = pd.DataFrame({R.ZONE_TEMP.value: convert(col, R.ZONE_TEMP, "degF")})
        if R.OCCUPANCY.value in ahu:
            zdf[R.OCCUPANCY.value] = ahu[R.OCCUPANCY.value]
        if R.SUPPLY_FAN_STATUS.value in ahu:          # zones are served only while the AHU runs
            zdf[R.SUPPLY_FAN_STATUS.value] = ahu[R.SUPPLY_FAN_STATUS.value]
        frames[zid] = EquipmentFrame(zid, "vav", zdf, points_used={R.ZONE_TEMP.value: col},
                                     role_sources={R.ZONE_TEMP.value: "explicit"}, parent_id="AHU")
    return frames


@dataclass
class ScenarioResult:
    scenario: str
    fault_class: str
    days_running: int = 0
    days_flagged: int = 0
    rule_days: Counter = field(default_factory=Counter)
    sensor_rule_days: Counter = field(default_factory=Counter)

    @property
    def flag_rate(self) -> float:
        return round(100.0 * self.days_flagged / self.days_running, 1) if self.days_running else 0.0

    def to_dict(self) -> Dict:
        return {"scenario": self.scenario, "fault_class": self.fault_class,
                "days_running": self.days_running, "days_flagged": self.days_flagged,
                "flag_rate_pct": self.flag_rate,
                "rules_firing_days": dict(self.rule_days.most_common()),
                "sensor_rules_firing_days": dict(self.sensor_rule_days.most_common())}


def _day_slices(frames: Dict[str, EquipmentFrame]) -> Iterable[Dict[str, EquipmentFrame]]:
    ahu = frames["AHU"].frame
    for day, _ in ahu.groupby(ahu.index.normalize()):
        end = day + pd.Timedelta(days=1)
        yield {k: EquipmentFrame(ef.equipment_id, ef.kind, ef.frame.loc[day:end - pd.Timedelta(seconds=1)].copy(),
                                 points_used=ef.points_used, role_sources=dict(ef.role_sources),
                                 design_attributes=ef.design_attributes, parent_id=ef.parent_id)
               for k, ef in frames.items()}


def evaluate_scenario(name: str, frames: Dict[str, EquipmentFrame], engine: FDDEngine,
                      include_zones: bool = False) -> ScenarioResult:
    res = ScenarioResult(name, scenario_of(name))
    status = R.SUPPLY_FAN_STATUS.value
    for day in _day_slices(frames):
        ahu = day["AHU"].frame
        if status not in ahu or not (ahu[status].fillna(0) > 0.5).any():
            continue                                   # AHU never ran that day
        res.days_running += 1
        if not include_zones:
            day = {"AHU": day["AHU"]}
        enrich_context(day)
        fired, sensor_fired = set(), set()
        for ef in day.values():
            for f in engine.evaluate(ef):
                if f.outcome is Outcome.FAIL:
                    (sensor_fired if f.family == "sensor" else fired).add(f.rule_id)
        for r in fired:
            res.rule_days[r] += 1
        for r in sensor_fired:
            res.sensor_rule_days[r] += 1
        if fired:
            res.days_flagged += 1
    return res


def run_lbnl_sdahu(data_dir: Path, *, engine: Optional[FDDEngine] = None, resample_seconds: int = 300,
                   include_zones: bool = False, limit_files: Optional[int] = None) -> Dict:
    engine = engine or FDDEngine(poll_seconds=float(resample_seconds))
    files = sorted(Path(data_dir).glob("*.csv"))[: limit_files or None]
    if not files:
        raise FileNotFoundError(f"no LBNL CSV files in {data_dir}")
    results = []
    for path in files:
        logger.info("benchmarking %s", path.name)
        frames = load_lbnl_sdahu(path, resample_seconds=resample_seconds)
        results.append(evaluate_scenario(path.stem, frames, engine, include_zones=include_zones))
    free = [r for r in results if r.fault_class == "fault_free"]
    by_class: Dict[str, List[ScenarioResult]] = {}
    for r in results:
        if r.fault_class != "fault_free":
            by_class.setdefault(r.fault_class, []).append(r)
    summary = {
        "dataset": "LBNL FDD Data Sets — single-duct AHU (DOI 10.25984/1881324)",
        "method": "per running day; flagged = any non-sensor rule confirmed a fault",
        "false_alarm_rate_pct": free[0].flag_rate if free else None,
        "detection_rate_pct_by_fault_class": {
            cls: round(sum(r.days_flagged for r in rs) * 100.0 / max(sum(r.days_running for r in rs), 1), 1)
            for cls, rs in sorted(by_class.items())},
        "scenarios": [r.to_dict() for r in results],
    }
    return summary


def to_markdown(summary: Dict) -> str:
    lines = [f"# ARVIS FDD benchmark — {summary['dataset']}", "",
             f"Method: {summary['method']}.", "",
             f"**False-alarm rate (fault-free year): {summary['false_alarm_rate_pct']}% of running days**", "",
             "| Fault class | Detection rate (running days) |", "|---|---|"]
    for cls, rate in summary["detection_rate_pct_by_fault_class"].items():
        lines.append(f"| {cls} | {rate}% |")
    lines += ["", "| Scenario | Class | Running days | Flagged | Rate | Top rules (days) |",
              "|---|---|---|---|---|---|"]
    for s in summary["scenarios"]:
        top = ", ".join(f"{k} ({v})" for k, v in list(s["rules_firing_days"].items())[:4]) or "—"
        lines.append(f"| {s['scenario']} | {s['fault_class']} | {s['days_running']} | "
                     f"{s['days_flagged']} | {s['flag_rate_pct']}% | {top} |")
    return "\n".join(lines) + "\n"


def _cli() -> int:
    ap = argparse.ArgumentParser(description="Benchmark ARVIS FDD on LBNL labelled data.")
    ap.add_argument("--lbnl-sdahu", required=True, help="Directory with the unzipped SDAHU *.csv files")
    ap.add_argument("--out", default="reports/fdd_benchmark_sdahu", help="Output path prefix (.json/.md)")
    ap.add_argument("--resample", type=int, default=300)
    ap.add_argument("--zones", action="store_true", help="Also evaluate the five zones (VAV-1 etc.)")
    ap.add_argument("--limit-files", type=int, default=None)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
    summary = run_lbnl_sdahu(Path(args.lbnl_sdahu), resample_seconds=args.resample,
                             include_zones=args.zones, limit_files=args.limit_files)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    out.with_suffix(".md").write_text(to_markdown(summary), encoding="utf-8")
    print(to_markdown(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
