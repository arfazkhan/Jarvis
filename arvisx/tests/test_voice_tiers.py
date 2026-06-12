"""Three-tier voice: resident / manager / technician renderers.

Verifies:
- Resident sees outcome language only (no asset IDs, no %, no confidence tags).
- Resident sees critical disruption phrase when CRITICAL risk present.
- Resident sees all-clear when no critical risks.
- Manager (default/viewer) gets standard digest with band labels.
- Technician (fm/owner) gets asset IDs and action details.
"""
from __future__ import annotations

from datetime import datetime

from arvisx.messaging import answer, _resident_summary, _tech_digest
from arvisx.models import (CommunityReport, Risk, ServiceHealth,
                            ServiceType, Severity, HealthBand)


def _make_report(*, critical_service: ServiceType | None = None,
                  warning_service: ServiceType | None = None) -> CommunityReport:
    risks = []
    if critical_service:
        risks.append(Risk(
            asset_id="XFER-PUMP-01", asset_name="Transfer Pump 1",
            service=critical_service, severity=Severity.CRITICAL,
            message="Transfer Pump 1 offline — sump level critical",
            detail="Inspect motor starter, check MCB on DB-3",
            confidence="High",
        ))
    if warning_service:
        risks.append(Risk(
            asset_id="BOOST-PUMP-02", asset_name="Booster Pump 2",
            service=warning_service, severity=Severity.WARNING,
            message="Booster Pump 2 runtime +43% above baseline",
            detail="Inspect bearings and mechanical seal",
            confidence="Medium",
        ))
    water_score = 70.0 if critical_service == ServiceType.WATER else 95.0
    water_band = HealthBand.CRITICAL if critical_service == ServiceType.WATER else HealthBand.HEALTHY
    svcs = [
        ServiceHealth(ServiceType.WATER, water_score, water_band, 2),
        ServiceHealth(ServiceType.POWER_BACKUP, 92.0, HealthBand.HEALTHY, 1),
        ServiceHealth(ServiceType.GAS, 88.0, HealthBand.HEALTHY, 1),
    ]
    score = 70.0 if risks else 95.0
    return CommunityReport(
        generated_at=datetime.now(),
        services=svcs,
        risks=risks,
        assets=[],
        readiness=score,
        readiness_band="Attention Required" if risks else "Healthy",
    )


# ── Resident tier ─────────────────────────────────────────────────────────

def test_resident_all_clear_no_asset_names():
    report = _make_report()
    res = answer("how is building", report, role="resident")
    t = res["text"]
    # no raw asset IDs or technical terms
    assert "XFER" not in t and "kW" not in t and "%" not in t
    assert "All services operating normally" in t or "normal" in t.lower()


def test_resident_critical_water_shows_disruption_phrase():
    report = _make_report(critical_service=ServiceType.WATER)
    res = answer("any issues?", report, role="resident")
    t = res["text"]
    assert "Water supply disruption" in t or "water supply" in t.lower()
    # must NOT expose asset ID or confidence tags
    assert "XFER-PUMP" not in t
    assert "[High]" not in t


def test_resident_warning_only_does_not_show_disruption():
    """Warnings are NOT surfaced to residents — only critical disruptions break through."""
    report = _make_report(warning_service=ServiceType.WATER)
    res = answer("status", report, role="resident")
    t = res["text"]
    # warning shouldn't trigger the bad phrase
    assert "disruption" not in t.lower()
    assert "Water supply normal" in t or "normal" in t.lower()


def test_resident_critical_count_shown_generically():
    report = _make_report(critical_service=ServiceType.WATER)
    t = answer("how is building", report, role="resident")["text"]
    # a count line like "1 issue(s) being addressed"
    assert "being addressed" in t or "issue" in t.lower()


def test_resident_no_confidence_tags():
    report = _make_report(critical_service=ServiceType.WATER)
    t = answer("issues", report, role="resident")["text"]
    for tag in ("[High]", "[Medium]", "[Low]", "confidence", "Confidence"):
        assert tag not in t, f"resident saw confidence tag: {tag!r}"


# ── Manager / viewer tier ─────────────────────────────────────────────────

def test_manager_gets_band_labels():
    report = _make_report(warning_service=ServiceType.WATER)
    res = answer("status", report, role="manager")
    t = res["text"]
    assert "Water" in t
    # standard digest shows band emoji or band label
    assert any(e in t for e in ("✅", "⚠️", "🚨"))


def test_viewer_same_as_manager():
    report = _make_report()
    res_v = answer("status", report, role="viewer")
    res_m = answer("status", report, role="manager")
    assert res_v["text"] == res_m["text"]


# ── Technician / FM / Owner tier ──────────────────────────────────────────

def test_tech_digest_shows_asset_id():
    report = _make_report(critical_service=ServiceType.WATER)
    t = _tech_digest(report)
    assert "XFER-PUMP-01" in t


def test_tech_digest_shows_action():
    report = _make_report(critical_service=ServiceType.WATER)
    t = _tech_digest(report)
    assert "Inspect" in t or "inspect" in t or "MCB" in t


def test_fm_role_gets_tech_voice():
    report = _make_report(critical_service=ServiceType.WATER)
    res = answer("status", report, role="fm")
    t = res["text"]
    assert "XFER-PUMP-01" in t


def test_owner_role_gets_tech_voice():
    report = _make_report(warning_service=ServiceType.WATER)
    res = answer("issues", report, role="owner")
    t = res["text"]
    assert "BOOST-PUMP-02" in t
    assert "[Medium]" in t


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for f in fns:
        f(); print(f"  ✅ {f.__name__}")
    print(f"PASS — {len(fns)} voice-tier tests")
