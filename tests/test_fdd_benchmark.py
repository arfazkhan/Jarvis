"""Phase 6 — LBNL benchmark harness, exercised on small files in the LBNL SDAHU format."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from agent_commercial.fdd.benchmark import load_lbnl_sdahu, run_lbnl_sdahu, scenario_of, to_markdown
from agent_commercial.semantics import PointRole as R


def _write(path: Path, leak: bool, days: int = 3, seed: int = 0):
    """Mimics the documented sequence: occupied 06–22 h, economizer below 60 °F OAT
    with the CHW valve closed; a 'leak' keeps cooling through the closed valve."""
    rng = np.random.default_rng(seed)
    t = pd.date_range("2026-04-01", periods=days * 1440, freq="1min")
    hour = t.hour + t.minute / 60
    occ = ((hour >= 6) & (hour < 22)).astype(float)
    oat = 55 + 12 * np.sin((hour - 9) / 24 * 2 * np.pi) + rng.normal(0, 0.3, len(t))
    rat = 72 + rng.normal(0, 0.2, len(t))
    econ = oat < 53                       # economizer alone can reach 55 °F supply here
    # Economizer modulates to a 54 °F mixed-air setpoint; otherwise minimum OA.
    target = np.clip((54.0 - rat) / (oat - rat), 0.1, 1.0)
    dmpr = np.where(occ > 0, np.where(econ, target, 0.1), 0.0)
    mat = dmpr * oat + (1 - dmpr) * rat + rng.normal(0, 0.2, len(t))
    vlv = np.where((occ > 0) & ~econ, 0.5, 0.0)
    sat = np.where(vlv > 0, 55.0, mat + 1.0) + rng.normal(0, 0.2, len(t))
    if leak:
        sat = np.where((occ > 0) & (vlv == 0), mat - 7.0, sat)
    df = pd.DataFrame({
        "Datetime": t.strftime("%m/%d/%Y %H:%M"),
        "SA_TEMP": sat, "SA_TEMPSPT": 55.0, "OA_TEMP": oat, "MA_TEMP": mat, "RA_TEMP": rat,
        "SF_SPD_DM": occ, "SF_CS": 0.6 * occ, "OA_DMPR_DM": dmpr, "CHWC_VLV_DM": vlv,
        "SA_SP": 1.6 * occ + rng.normal(0, 0.02, len(t)), "SA_SPSPT": 1.6,
        "SA_CFM": 12000 * occ, "OA_CFM": 12000 * occ * dmpr, "SF_WAT": 5000 * occ,
        "SYS_CTL": occ, "ZONE_TEMP_1": 73 + rng.normal(0, 0.3, len(t)),
    })
    df.to_csv(path, index=False)


@pytest.fixture
def lbnl_dir(tmp_path):
    _write(tmp_path / "AHU_annual.csv", leak=False)
    _write(tmp_path / "coi_leakage_050_annual.csv", leak=True, seed=1)
    return tmp_path


def test_scenario_names_follow_the_documented_inventory():
    assert scenario_of("AHU_annual") == "fault_free"
    assert scenario_of("coi_leakage_010_annual") == "cooling_valve_leak"
    assert scenario_of("damper_stuck_100_annual_short") == "oa_damper_stuck"
    assert scenario_of("oa_bias_-4_annual") == "oat_sensor_bias"


def test_loader_maps_documented_points_to_si_roles(lbnl_dir):
    frames = load_lbnl_sdahu(lbnl_dir / "AHU_annual.csv")
    ahu = frames["AHU"].frame
    assert ahu[R.SUPPLY_AIR_TEMP_SP.value].iloc[100] == pytest.approx(12.7778, abs=1e-3)   # 55 °F
    assert ahu[R.DUCT_STATIC_PRESSURE_SP.value].iloc[100] == pytest.approx(1.6 * 249.0889)
    assert ahu[R.COOLING_VALVE.value].max() == pytest.approx(0.5)                          # command
    assert frames["AHU"].points_used[R.COOLING_VALVE.value] == "CHWC_VLV_DM"
    assert "ZONE-1" in frames and frames["ZONE-1"].parent_id == "AHU"
    assert len(ahu) == 3 * 288                                                             # 5-min grid


def test_benchmark_separates_fault_free_from_leak(lbnl_dir, tmp_path):
    summary = run_lbnl_sdahu(lbnl_dir)
    by = {s["scenario"]: s for s in summary["scenarios"]}
    assert by["AHU_annual"]["days_running"] == 3
    assert summary["false_alarm_rate_pct"] == 0.0, by["AHU_annual"]["rules_firing_days"]
    assert summary["detection_rate_pct_by_fault_class"]["cooling_valve_leak"] == 100.0
    assert "VLV-1" in by["coi_leakage_050_annual"]["rules_firing_days"]
    md = to_markdown(summary)
    assert "False-alarm rate" in md and "cooling_valve_leak | 100.0%" in md
