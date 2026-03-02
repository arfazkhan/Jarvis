"""
Phase 4 SONA Test Suite
========================
Tests every Deep SONA feature end-to-end:

1. Trajectory Logging — verifies Queen saves state to DB after a query
2. EWC++ Veto Penalty — sends an actionable query and checks calibration weights updated
3. EWC++ Hallucination Penalty — injects a low-score validation and checks weight decremented
4. Knowledge Distiller — seeds decisions table then runs distillation, checks Skillbook output
5. Dynamic Routing (MoE) — confirms EWC weight suppression shows up in route logs
"""

import asyncio
import json
import logging
import os
import sys
import time

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("test_phase4")

SEPARATOR = "=" * 70

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

async def get_skillbook():
    from agent_commercial.skillbook import get_skillbook as _get
    sb = _get("default")
    await sb.ensure_initialized()
    return sb

def get_meta():
    from agent_cognitive.meta_cognition import MetaCognition
    return MetaCognition(building_id="default")


# ─────────────────────────────────────────────────────────────────────────────
# TEST 1: Trajectory Logging
# ─────────────────────────────────────────────────────────────────────────────

async def test_trajectory_logging():
    print(f"\n{SEPARATOR}")
    print("TEST 1: Trajectory Logging")
    print(SEPARATOR)

    sb = await get_skillbook()
    meta = get_meta()

    # Record a fake trajectory for a "read-only" query
    trajectory = {
        "pre_state": {"query": "What is the current energy consumption?", "context": {}},
        "action": {"Energy_Agent": "Energy at 1,200 kWh/day. 15% above benchmark."},
        "post_state": "Current energy consumption is 1,200 kWh/day, 15% above the GSAS benchmark."
    }
    decision_id = meta.record_decision(
        context={"trajectory": trajectory},
        chosen_action="Synthesized Advice",
        alternatives=["Energy_Agent", "Alarm_Agent"],
        confidence=1.0,
        reasoning="Informational query synthesized."
    )
    print(f"  ✅ Decision recorded with ID: {decision_id}")

    # Wait a beat and fetch from DB
    await asyncio.sleep(0.3)
    decisions = await sb.get_recent_decisions(limit=5)
    found = any(d.get("chosen_action") == "Synthesized Advice" for d in decisions)
    if found:
        print("  ✅ Trajectory found in BuildingSkillbook decisions table.")
    else:
        print("  ❌ FAIL: Trajectory NOT found in DB. Check skillbook.log_decision().")
    return found


# ─────────────────────────────────────────────────────────────────────────────
# TEST 2: EWC++ Veto Penalty
# ─────────────────────────────────────────────────────────────────────────────

def test_ewc_veto_penalty():
    print(f"\n{SEPARATOR}")
    print("TEST 2: EWC++ Veto Penalty")
    print(SEPARATOR)

    meta = get_meta()
    rule_name = "test_veto_Alarm_Agent_Energy_Agent"

    # First application — fresh rule
    meta.update_ewc_weights(rule_name=rule_name, new_weight=1.0, importance=1.5)
    rules = meta.get_active_calibration_rules()

    if rule_name in rules:
        weight = rules[rule_name].get("weight_adjustment", 0)
        fisher = rules[rule_name].get("fisher_information", 0)
        print(f"  ✅ EWC++ rule created: '{rule_name}'")
        print(f"     Weight={weight:.3f}, Fisher Information={fisher:.3f}")
        
        # Apply another veto — weight should be dampened (EWC++ prevents catastrophic forgetting)
        meta.update_ewc_weights(rule_name=rule_name, new_weight=0.0, importance=2.0)
        rules_after = meta.get_active_calibration_rules()
        new_weight = rules_after[rule_name].get("weight_adjustment", 0)
        print(f"     After 2nd update (new_weight=0.0, high importance): Weight={new_weight:.3f}")
        if new_weight > 0:
            print("  ✅ EWC++ damping confirmed — high Fisher Info protected the original weight.")
            return True
        else:
            print("  ⚠️  Weight dropped below 0 — Fisher damping may need tuning.")
            return False
    else:
        print("  ❌ FAIL: EWC++ rule not found in calibration_rules.")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# TEST 3: EWC++ Hallucination Penalty (TruthValidator integration)
# ─────────────────────────────────────────────────────────────────────────────

async def test_ewc_hallucination_penalty():
    print(f"\n{SEPARATOR}")
    print("TEST 3: EWC++ Hallucination Penalty (TruthValidator)")
    print(SEPARATOR)

    meta = get_meta()
    rule_name = "hallucination_penalty_rule"

    # Read baseline weight
    rules_before = meta.get_active_calibration_rules()
    weight_before = rules_before.get(rule_name, {}).get("weight_adjustment", 0.0)
    print(f"  Baseline hallucination weight: {weight_before:.3f}")

    # Simulate the TruthValidator detecting a hallucination
    meta.update_ewc_weights(rule_name=rule_name, new_weight=-0.5, importance=2.0)

    rules_after = meta.get_active_calibration_rules()
    weight_after = rules_after.get(rule_name, {}).get("weight_adjustment", 0.0)
    print(f"  After hallucination penalty: {weight_after:.3f}")

    if weight_after < weight_before or weight_after < 0:
        print("  ✅ Hallucination penalty applied correctly (weight decreased).")
        return True
    else:
        print("  ⚠️  Weight did not decrease — check EWC++ formula for negative inputs.")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# TEST 4: Knowledge Distiller
# ─────────────────────────────────────────────────────────────────────────────

async def test_knowledge_distiller():
    print(f"\n{SEPARATOR}")
    print("TEST 4: Knowledge Distiller")
    print(SEPARATOR)

    sb = await get_skillbook()
    meta = get_meta()

    # Seed the decisions table with 10 veto-pattern records
    print("  Seeding 10 veto decisions for Alarm_Agent...")
    for i in range(10):
        await sb.log_decision(
            decision_id=f"seed-veto-{i}-{int(time.time())}",
            context={},
            chosen_action="Action Vetoed",
            alternatives=["Energy_Agent", "Alarm_Agent"],
            confidence=0.0,
            reasoning="Seeded veto for distiller test",
            trajectory={
                "pre_state": {"query": "Reduce fan speed by 50%", "context": {}},
                "action": {
                    "Energy_Agent": "Propose reducing fan speed by 50%",
                    "Alarm_Agent": "VOTE: VETO - CO2 safety limits would be breached"
                },
                "post_state": "Action VETOED"
            }
        )

    print("  Running KnowledgeDistiller...")
    from agent_cognitive.distiller import KnowledgeDistiller
    distiller = KnowledgeDistiller(building_id="default")
    result = await distiller.run_distillation(inject_prompts=False)  # skip file writing in test
    
    print(f"  Distillation result: {json.dumps(result, indent=4)}")

    if result.get("distilled", 0) >= 1:
        print(f"  ✅ Distiller correctly identified and distilled {result['distilled']} pattern(s)!")
        return True
    else:
        print(f"  ⚠️  No patterns distilled. May need more seeded decisions or lower threshold.")
        print(f"      Patterns found: {result.get('patterns_found', 0)}, Decisions analyzed: {result.get('decisions_analyzed', 0)}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# TEST 5: Dynamic Routing (MoE Suppression Log)
# ─────────────────────────────────────────────────────────────────────────────

async def test_dynamic_routing():
    print(f"\n{SEPARATOR}")
    print("TEST 5: Dynamic Routing (Mixture of Experts)")
    print(SEPARATOR)

    meta = get_meta()

    # Force the hallucination penalty to a very negative value to trigger MoE suppression log
    meta.update_ewc_weights(rule_name="hallucination_penalty_rule", new_weight=-2.0, importance=0.1)
    rules = meta.get_active_calibration_rules()
    weight = rules.get("hallucination_penalty_rule", {}).get("weight_adjustment", 0)
    print(f"  Hallucination penalty forced to: {weight:.3f} (should be < -0.3)")

    # Import the Queen and check if it reads the weight
    from arvis_core.swarm.queen import QueenCoordinator
    queen = QueenCoordinator()

    # Run _route_intent — it should log the MoE suppression warning
    import logging
    log_records = []
    class CapturingHandler(logging.Handler):
        def emit(self, record):
            log_records.append(record.getMessage())

    handler = CapturingHandler()
    logging.getLogger("arvis.swarm.queen").addHandler(handler)

    _ = await queen._route_intent("What is the current energy status?")
    
    logging.getLogger("arvis.swarm.queen").removeHandler(handler)

    moe_triggered = any("Hallucination penalty is high" in msg for msg in log_records)
    if moe_triggered:
        print("  ✅ MoE suppression warning triggered correctly by high hallucination penalty!")
        return True
    else:
        print(f"  ⚠️  MoE warning not found in logs (weight={weight:.3f}). Check threshold logic.")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# MAIN RUNNER
# ─────────────────────────────────────────────────────────────────────────────

async def main():
    print(f"\n{'#' * 70}")
    print("  ARVIS PHASE 4 (SONA CONTINUOUS LEARNING) — TEST SUITE")
    print(f"{'#' * 70}")

    results = {}

    results["Trajectory Logging"] = await test_trajectory_logging()
    results["EWC++ Veto Penalty"] = test_ewc_veto_penalty()
    results["EWC++ Hallucination Penalty"] = await test_ewc_hallucination_penalty()
    results["Knowledge Distiller"] = await test_knowledge_distiller()
    results["Dynamic Routing (MoE)"] = await test_dynamic_routing()

    print(f"\n{'#' * 70}")
    print("  FINAL RESULTS")
    print(f"{'#' * 70}")
    all_passed = True
    for name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}  {name}")
        if not passed:
            all_passed = False

    print(f"\n  Overall: {'✅ ALL TESTS PASSED' if all_passed else '⚠️  SOME TESTS FAILED — review output above'}")
    print(f"{'#' * 70}\n")


if __name__ == "__main__":
    asyncio.run(main())
