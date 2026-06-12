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

from arvisx.messaging import (answer, _resident_summary, _tech_digest,
                              _manager_phrasing, format_alert_resident, pending_alerts)
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


# ── Gap 2: resident single-service Q&A ────────────────────────────────────

def test_resident_pool_question_returns_only_pool_line():
    report = _make_report()  # all healthy
    t = answer("is the pool open?", report, role="resident")["text"]
    assert "Pool operational" in t
    # must NOT dump the whole building summary
    assert "Water supply" not in t
    assert "Backup power" not in t


def test_resident_water_question_critical_shows_disruption():
    report = _make_report(critical_service=ServiceType.WATER)
    t = answer("is water ok?", report, role="resident")["text"]
    assert "Water supply disruption" in t
    assert "XFER" not in t and "%" not in t


def test_resident_gas_question_warning_stays_normal():
    """A warning on gas must not flip the resident line to disruption."""
    report = _make_report(warning_service=ServiceType.GAS)
    t = answer("gas status", report, role="resident")["text"]
    assert "Cooking gas supply normal" in t
    assert "disruption" not in t.lower() and "do not use" not in t.lower()


# ── Gap 3: manager plain-language softener ────────────────────────────────

def _risk(msg, name="Booster Pump 2", sev=Severity.WARNING, detail=""):
    return Risk(asset_id="BP-2", asset_name=name, service=ServiceType.WATER,
                severity=sev, message=msg, detail=detail, confidence="Medium")


def test_manager_softens_power_creep():
    out = _manager_phrasing(_risk("Booster Pump 2 power creep (3.2σ above its own normal)"))
    assert "working harder than usual" in out
    assert "σ" not in out and "creep" not in out.lower()


def test_manager_softens_short_cycling():
    out = _manager_phrasing(_risk("Booster Pump 2 short-cycling (5.1 starts/h)"))
    assert "switching on and off too often" in out
    assert "starts/h" not in out


def test_manager_strips_math_noise_on_unmatched():
    out = _manager_phrasing(_risk("Booster Pump 2 vibration spike (4.0σ, 12.3 kW)"))
    # no rule matches → keep message but drop the math parenthetical
    assert "vibration spike" in out
    assert "σ" not in out and "kW" not in out


def test_manager_issues_uses_softened_text():
    report = _make_report()
    report.risks.append(_risk("Booster Pump 2 power creep (3.2σ above its own normal)"))
    t = answer("any issues?", report, role="manager")["text"]
    assert "working harder than usual" in t
    assert "σ" not in t


def test_technician_keeps_raw_jargon():
    report = _make_report()
    report.risks.append(_risk("Booster Pump 2 power creep (3.2σ above its own normal)"))
    t = answer("any issues?", report, role="fm")["text"]
    # technician sees the raw, precise text — softener must NOT touch the tech tier
    assert "power creep" in t


# ── Gap 1: tiered alert push ──────────────────────────────────────────────

def test_resident_alert_only_for_critical():
    crit = _risk("Transfer Pump offline", sev=Severity.CRITICAL)
    crit.service = ServiceType.WATER
    warn = _risk("Booster Pump 2 power creep", sev=Severity.WARNING)
    assert format_alert_resident(crit) != ""
    assert "Water supply disruption" in format_alert_resident(crit)
    assert format_alert_resident(warn) == ""   # warnings never reach residents


def test_pending_alerts_carries_resident_text():
    report = _make_report(critical_service=ServiceType.WATER)
    alerts, _sent = pending_alerts(report, set(), [], None)
    assert alerts, "a CRITICAL risk should produce an alert"
    crit_alert = next(a for a in alerts if a["severity"] == "critical")
    assert crit_alert["resident_text"]               # populated for residents
    assert "XFER-PUMP" not in crit_alert["resident_text"]   # but no asset detail
    assert "Confidence" not in crit_alert["resident_text"]


# ── Fix 1: resident work-order reply must be honest ───────────────────────

def test_resident_work_order_reply_is_honest():
    report = _make_report()
    res = answer("create work order", report, role="resident")
    t = res["text"]
    # must not claim anything was recorded/forwarded — nothing is
    for false_claim in ("noted", "they'll see", "recorded", "sent to", "forwarded"):
        assert false_claim not in t.lower(), f"resident WO reply claims: {false_claim!r}"
    assert "facility desk" in t.lower()
    assert "action" not in res                # no WO action fires for residents


# ── Fix 2: softener consistency across tiers ──────────────────────────────

def test_manager_fix_intent_softened():
    report = _make_report()
    report.risks.append(_risk("Booster Pump 2 power creep (3.2σ above its own normal)",
                              detail="Trend power and inspect bearings."))
    t = answer("how to fix", report, role="manager")["text"]
    assert "working harder than usual" in t
    assert "σ" not in t and "power creep" not in t.lower()
    assert "Trend power and inspect bearings." in t     # action stays precise


def test_tech_fix_intent_keeps_raw():
    report = _make_report()
    report.risks.append(_risk("Booster Pump 2 power creep (3.2σ above its own normal)",
                              detail="Trend power and inspect bearings."))
    t = answer("how to fix", report, role="fm")["text"]
    assert "power creep" in t and "σ" in t


def test_tech_service_query_keeps_raw():
    report = _make_report()
    report.risks.append(_risk("Booster Pump 2 power creep (3.2σ above its own normal)"))
    t = answer("water status", report, role="fm")["text"]
    assert "power creep" in t                 # raw, not "working harder than usual"


def test_manager_service_query_softened():
    report = _make_report()
    report.risks.append(_risk("Booster Pump 2 power creep (3.2σ above its own normal)"))
    t = answer("water status", report, role="manager")["text"]
    assert "working harder than usual" in t and "σ" not in t


# ── Fix 3: resident push dedup per service ────────────────────────────────

def test_resident_push_deduped_per_service():
    report = _make_report(critical_service=ServiceType.WATER)
    # second distinct CRITICAL water risk
    report.risks.append(_risk("Overhead Tank 1 level critically low", name="Overhead Tank 1",
                              sev=Severity.CRITICAL))
    alerts, sent = pending_alerts(report, set(), [], None)
    crits = [a for a in alerts if a["severity"] == "critical"]
    assert len(crits) == 2, "both technical alerts must still go to ops"
    with_resident = [a for a in crits if a["resident_text"]]
    assert len(with_resident) == 1, "residents get the water disruption ONCE, not per risk"
    assert "resident::water" in sent


def test_resident_push_dedup_persists_across_polls():
    report = _make_report(critical_service=ServiceType.WATER)
    _alerts1, sent = pending_alerts(report, set(), [], None)
    # new critical water risk on the NEXT poll — resident already pinged for water
    report.risks.append(_risk("Overhead Tank 1 level critically low", name="Overhead Tank 1",
                              sev=Severity.CRITICAL))
    alerts2, _sent2 = pending_alerts(report, sent, [], None)
    new_crit = [a for a in alerts2 if a["severity"] == "critical"]
    assert new_crit, "the new risk still alerts ops"
    assert all(not a["resident_text"] for a in new_crit), "no repeat resident ping for water"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for f in fns:
        f(); print(f"  ✅ {f.__name__}")
    print(f"PASS — {len(fns)} voice-tier tests")
