"""
ArvisX real-LLM end-to-end — the SAME lifecycle, but with the LLM reasoning layer
ON (ARVIS_X_LLM=1, real provider via the repo .env). Proves the LLM-on-top works
AND stays grounded: the model proposes, the deterministic floor disposes
(evidence-binding drops any asset id the model invents).

Network + provider creds required → auto-SKIPS under pytest when unavailable, so it
never breaks the offline suite. Run it live as a story:

    python arvisx/tests/test_full_lifecycle_llm_e2e.py

What it checks beyond the deterministic e2e:
  - UnifiedLLM constructs from the vendored commercial stack
  - reasoning.correlate + ask actually route to the LLM (source == "llm")
  - GROUNDING HOLDS: every asset id the LLM cites/links is a REAL active-risk id
    (evidence-bound) — no hallucinated ids reach the operator
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path


def _load_env_and_llm():
    """Load repo .env, enable the LLM flag, build ArvisX's own LLM client (K2Think by
    default). Returns (llm, why_skip)."""
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    except Exception:
        pass
    os.environ["ARVIS_X_LLM"] = "1"
    os.environ.setdefault("ARVISX_LLM_PROVIDER", "k2think")
    from arvisx.llm_client import make_llm
    llm = make_llm()
    if llm is None:
        return None, f"no usable {os.environ.get('ARVISX_LLM_PROVIDER')} credentials"
    return llm, None


def _degraded_state():
    from arvisx.health import build_report
    from arvisx.simulator import inject_prd_scenario
    assets = inject_prd_scenario()
    report = build_report(assets, virtual=True, water=True)
    return assets, report.risks


def _run(verbose=False):
    def say(*a):
        if verbose:
            print(*a)

    llm, why = _load_env_and_llm()
    if llm is None:
        say(f"SKIP — {why}")
        return None
    say(f"[0] LLM up  provider={getattr(llm, 'provider', '?')} "
        f"model={getattr(llm, 'model', '?')}")

    from arvisx.reasoning import ask, correlate
    assets, risks = _degraded_state()
    valid_ids = {a.asset_id for a in assets}
    say(f"[1] STATE  {len(risks)} active risks across {len(assets)} assets")
    for r in risks[:6]:
        say(f"    - [{r.severity.value}] {r.message}")

    # ── correlate (real LLM) ─────────────────────────────────────────────
    corr = asyncio.run(correlate(assets, risks, llm=llm))
    say(f"\n[2] CORRELATE ({corr.source})  independent={corr.independent} "
        f"conf={corr.confidence}")
    say(f"    common_cause: {corr.common_cause}")
    say(f"    linked: {corr.linked_assets}")
    say(f"    rationale: {corr.rationale[:160]}")
    assert corr.source == "llm", "correlate should have used the real LLM"
    # GROUNDING: every linked id is a real one (evidence-bound, no hallucination)
    assert all(a in valid_ids for a in corr.linked_assets), "linked ids must be real"

    # ── ask (real LLM) ───────────────────────────────────────────────────
    ans = asyncio.run(ask("Which system is the biggest risk right now and why?",
                          assets, risks, llm=llm))
    say(f"\n[3] ASK ({ans.source})  conf={ans.confidence}")
    say(f"    answer: {ans.answer[:240]}")
    say(f"    cited: {ans.cited}")
    assert ans.source == "llm", "ask should have used the real LLM"
    assert ans.answer and len(ans.answer) > 10, "expected a substantive answer"
    assert all(a in valid_ids for a in ans.cited), "cited ids must be real (grounded)"

    say("\nRESULT: PASS — real LLM reasoning works AND stays grounded "
        "(LLM proposes, floor disposes, no invented asset ids).\n")
    return True


def test_full_lifecycle_llm_e2e():
    import pytest
    result = _run(verbose=False)
    if result is None:
        pytest.skip("real LLM not available (no creds / SDK / stack)")
    assert result is True


if __name__ == "__main__":
    out = _run(verbose=True)
    raise SystemExit(0 if out in (True, None) else 1)
