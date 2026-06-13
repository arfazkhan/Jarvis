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
    import random
    report = _make_report()
    random.seed(7)                      # digest phrasing varies per send (anti-ban);
    res_v = answer("status", report, role="viewer")
    random.seed(7)                      # pin the RNG to compare the tier, not the variant
    res_m = answer("status", report, role="manager")
    assert res_v["text"] == res_m["text"]


# ── Technician / FM / Owner tier ──────────────────────────────────────────

def test_tech_digest_is_clean_overview():
    # The ops digest is a scannable overview — readiness + tiles + a worst-issue
    # teaser + a prompt — NOT a wall of per-asset detail (that lives in 'issues').
    report = _make_report(critical_service=ServiceType.WATER)
    t = _tech_digest(report)
    assert "Community Readiness" in t
    assert "Reply" in t and ("issues" in t.lower())


def test_tech_issues_show_asset_id_and_action():
    report = _make_report(critical_service=ServiceType.WATER)
    t = answer("issues", report, role="fm")["text"]
    assert "XFER-PUMP-01" in t
    assert "Inspect" in t or "inspect" in t or "MCB" in t


def test_fm_role_gets_tech_voice():
    # FM 'issues' is the raw tech view (asset id present); the digest is the overview.
    report = _make_report(critical_service=ServiceType.WATER)
    assert "XFER-PUMP-01" in answer("issues", report, role="fm")["text"]
    assert "Community Readiness" in answer("status", report, role="fm")["text"]


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


# ── Fix 1: resident work-order request is actually RECORDED ───────────────

def test_resident_work_order_returns_record_action():
    """Resident WO → action for the API to record. Text stays EMPTY here: the
    confirmation is only written after the save succeeds (honesty ordering)."""
    report = _make_report()
    res = answer("create work order: pool light broken", report, role="resident")
    assert res.get("action") == "resident_request"
    assert res["text"] == ""                       # no claim before the save
    assert "pool light broken" in res["request_text"]


def test_resident_request_persistence_roundtrip(tmp_path):
    from arvisx.persistence import ArvisxDb
    db = ArvisxDb(str(tmp_path / "rr.db"))
    rid = db.save_resident_request("919048057376", "pool light broken near steps")
    assert rid >= 1
    open_reqs = db.resident_requests(status="open")
    assert len(open_reqs) == 1
    assert open_reqs[0]["text"] == "pool light broken near steps"
    assert open_reqs[0]["by_user"] == "919048057376"
    db.set_resident_request_status(rid, "notified")
    assert db.resident_requests(status="open") == []
    assert len(db.resident_requests(status="notified")) == 1


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


# ── Phase A anti-ban: phrasing variants never lose facts or keywords ──────

def test_digest_varies_but_facts_constant():
    from arvisx.messaging import daily_digest, _DIGEST_HEADERS
    report = _make_report(warning_service=ServiceType.WATER)
    seen = set()
    for _ in range(40):
        t = daily_digest(report)
        seen.add(t.split("\n")[0])
        assert t.split("\n")[0] in _DIGEST_HEADERS
        assert "Community Readiness: *70%*" in t      # the number NEVER varies
        assert "1" in t.split("\n")[-1]               # issue count present
    assert len(seen) > 1, "header must actually vary across sends"


def test_alert_variants_keep_message_confidence_and_cta():
    from arvisx.messaging import format_alert
    r = _risk("Booster Pump 2 power creep (3.2σ above its own normal)",
              detail="Trend power and inspect bearings.")
    seen = set()
    for _ in range(40):
        t = format_alert(r)
        seen.add(t)
        assert "Booster Pump 2 power creep" in t       # fact verbatim
        assert "Confidence: Medium" in t
        assert "create work order" in t.lower()        # parseable CTA in EVERY variant
    assert len(seen) > 1


def test_resident_push_suffix_varies_but_phrase_intact():
    crit = _risk("Transfer Pump offline", sev=Severity.CRITICAL)
    seen = set()
    for _ in range(40):
        t = format_alert_resident(crit)
        seen.add(t)
        assert t.startswith("🚨 Water supply disruption — building team is on it")
    assert len(seen) > 1


def test_checklist_prompts_keep_reply_syntax(tmp_path):
    from arvisx.persistence import ArvisxDb
    from arvisx.checklist import pending_prompts, _PROMPT_PREFIXES
    db = ArvisxDb(str(tmp_path / "cl.db"))
    prefixes_seen = set()
    for _ in range(30):
        for p in pending_prompts(db):
            assert f"ok {p['item_id']}" in p["prompt"], "reply syntax must stay verbatim"
            assert f"issue {p['item_id']}" in p["prompt"]
            prefixes_seen.add(p["prompt"].split(":")[0] + ":")
    assert prefixes_seen <= set(_PROMPT_PREFIXES)
    assert len(prefixes_seen) > 1, "prompt prefix must vary across days"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for f in fns:
        f(); print(f"  ✅ {f.__name__}")
    print(f"PASS — {len(fns)} voice-tier tests")
