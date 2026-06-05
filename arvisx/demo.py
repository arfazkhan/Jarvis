"""
ArvisX Phase-0 demo — render the PRD MVP dashboard from simulated signals.

Run:  python -m arvisx.demo            # PRD fault scenario
      python -m arvisx.demo --healthy  # nominal community

Proves end-to-end (zero hardware, zero LLM): fragmented residential signals →
per-asset health → service-level roll-up → Community Overview + Active Risks +
Asset Explorer. This is the residential equivalent of the commercial demo flow.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

from arvisx.health import build_report
from arvisx.models import CommunityReport, Severity
from arvisx.simulator import healthy_community, inject_prd_scenario

_BAND_ICON = {"Healthy": "🟢", "Attention Required": "🟡", "Critical": "🔴"}
_SEV_ICON = {Severity.CRITICAL: "🔴 CRITICAL", Severity.WARNING: "🟠 WARNING",
             Severity.MAINTENANCE: "🔧 MAINTENANCE", Severity.INFO: "ℹ️  INFO"}
_SVC_LABEL = {"water": "Water Service", "power_backup": "Power Backup",
              "pool": "Pool Operations", "stp": "STP", "fire": "Fire Readiness"}


def render(report: CommunityReport) -> str:
    L: list[str] = []
    L.append("=" * 70)
    L.append("  ARVIS  ·  COMMUNITY OPERATIONS OVERVIEW")
    L.append(f"  generated {report.generated_at:%Y-%m-%d %H:%M}")
    L.append("=" * 70)

    # ── Community Overview (service tiles) ──────────────────────────────
    L.append("\n  COMMUNITY OVERVIEW")
    for s in report.services:
        icon = _BAND_ICON.get(s.band.value, "·")
        worst = f"  (weakest: {s.worst_asset})" if s.worst_asset else ""
        L.append(f"    {icon}  {_SVC_LABEL.get(s.service.value, s.service.value):<16} "
                 f"{s.band.value:<20} score {s.score:.0f}{worst}")

    # ── Active Risks ────────────────────────────────────────────────────
    L.append("\n  ACTIVE RISKS")
    if not report.risks:
        L.append("    none — all systems nominal")
    for r in report.risks:
        L.append(f"    {_SEV_ICON.get(r.severity, ''):<14} {r.message}")
        if r.detail:
            L.append(f"                   ↳ {r.detail}")

    # ── Asset Explorer ──────────────────────────────────────────────────
    L.append("\n  ASSET EXPLORER")
    L.append(f"    {'Asset':<26}{'Status':<24}{'Health':<10}{'Runtime':<10}Next Maint.")
    L.append("    " + "-" * 84)
    for a in sorted(report.assets, key=lambda x: x.score):
        icon = _BAND_ICON.get(a.band.value, "·")
        nm = a.next_maintenance_due.strftime("%Y-%m-%d") if a.next_maintenance_due else "—"
        rt = f"{a.runtime_hours:.0f}h" if a.runtime_hours else "—"
        L.append(f"    {a.name:<26}{a.status[:22]:<24}{icon} {a.score:>4.0f}  {rt:<10}{nm}")
    L.append("=" * 70)
    return "\n".join(L)


def render_advisory(adv) -> str:
    L = [f"\n  🔎 ADVISORY — {adv.asset_name}   [{adv.source}]",
         f"     Root cause : {adv.root_cause}",
         f"     Confidence : {adv.confidence_band}  |  confirmed={adv.confirmed}",
         f"     Action     : {adv.recommended_action}"]
    if adv.hypotheses:
        L.append("     Ranked differential:")
        for h in adv.hypotheses:
            L.append(f"       • p={h.probability:.2f}  {h.label}")
            if h.discriminating_test:
                L.append(f"                 test: {h.discriminating_test}")
    L.append(f"     Summary    : {adv.plain_summary}")
    return "\n".join(L)


def main() -> int:
    healthy = "--healthy" in sys.argv
    advise = "--advise" in sys.argv
    assets = healthy_community() if healthy else inject_prd_scenario()
    report = build_report(assets, now=datetime.now())
    print(render(report))

    if advise:
        import asyncio
        from arvisx.advisory import investigate_asset
        from arvisx.health import assess_asset
        llm = None
        if os.environ.get("ARVIS_X_LLM", "").strip() in ("1", "true", "True"):
            try:
                from arvisx.llm_env import load_arvis_env
                load_arvis_env()   # provider keys (K2THINK/BEDROCK) from repo .env
                from agent_unified.llm import UnifiedLLM
                llm = UnifiedLLM()
            except Exception as e:
                print(f"[warn] LLM requested but UnifiedLLM init failed: {e}")
        flagged_ids = {s.worst_asset for s in report.services if s.band.value != "Healthy"}
        flagged = [a for a in assets if a.name in flagged_ids]
        print("\n" + "=" * 70 + "\n  GROUNDED ADVISORIES (flagged assets)\n" + "=" * 70)

        async def _run():
            for a in flagged:
                _, rks = assess_asset(a, datetime.now())
                adv = await investigate_asset(a, rks, llm=llm)
                print(render_advisory(adv))
        asyncio.run(_run())
    # Machine summary for assertions / API later.
    crit = sum(1 for r in report.risks if r.severity == Severity.CRITICAL)
    warn = sum(1 for r in report.risks if r.severity == Severity.WARNING)
    maint = sum(1 for r in report.risks if r.severity == Severity.MAINTENANCE)
    attention = [s.service.value for s in report.services if s.band.value != "Healthy"]
    print(f"\n[summary] assets={len(report.assets)} risks={len(report.risks)} "
          f"(crit={crit} warn={warn} maint={maint}) services_needing_attention={attention}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
