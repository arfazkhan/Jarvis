"""
Default diagnostic knowledge per FDD rule.

Hypotheses = H1 "spurious" + the rule's root_cause_candidates (H2, H3, …).
Evidence = generic items for every rule + curated, discriminating items for
the rules that matter most in Gulf buildings.

``auto`` tells ARVIS how to answer an item from data it already has — other
rule outcomes on the same unit, its parent AHU, the plant, sensor validation,
the commissioned design, or case history — so the operator is only asked what
the data cannot settle. (ZandrEA asks a human every question.)

Auto forms:
  ("sensor_invalid",)                       a sensor this rule uses failed validation
  ("fault_pct_ge", pct)                     fault present ≥ pct % of running time
  ("previous_case",)                        same fault confirmed on this unit before
  ("rule", (rule_ids), "fail")              one of these rules failed on this unit
  ("parent_rule", (rule_ids), "fail")       … on the unit's parent (e.g. its AHU)
  ("building_rule", (rule_ids), "fail")     … on any unit in the building
  ("design", key, value)                    commissioned design attribute equals value
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from agent_commercial.fdd.diagnosis.kb import SPURIOUS, EvidenceItem, Hypothesis, RuleKB
from agent_commercial.fdd.rules import RULES_BY_ID

_SPURIOUS_LABEL = "spurious — the rule misfired; adjust its parameters"

# Curated items: (id, question, {label keyword → link strength}, auto)
# Keywords are matched against the rule's root_cause_candidates labels.
_Curated = List[Tuple[str, str, Dict[str, str], tuple]]

_LEAK: _Curated = [
    ("E_ISOLATE", "With the coil's CHW isolation valve shut, does the cooling across the coil stop?",
     {"passing": "requires", "actuator": "contradicts", "sensor": "excludes"}, None),
    ("E_FEEDBACK", "Does the valve position feedback read closed when the fault is present?",
     {"passing": "supports", "actuator": "contradicts"}, None),
]
_CURATED: Dict[str, _Curated] = {
    "FC14": _LEAK,
    "VLV-1": _LEAK,
    "FC13": [
        ("E_PLANT", "Is the chilled-water plant failing a supply or ΔT rule (CHW-1 / CHW-3 / DC-DT-1)?",
         {"chilled-water supply": "supports", "coil fouled": "contradicts"},
         ("building_rule", ("CHW-1", "CHW-3", "DC-DT-1"), "fail")),
        ("E_VALVE_FULL", "Does the cooling valve position feedback actually reach fully open?",
         {"not opening": "contradicts", "coil fouled": "supports", "undersized": "supports"}, None),
        ("E_FILTER", "Has the filter / coil pressure drop risen over recent weeks?",
         {"coil fouled": "supports", "undersized": "contradicts"}, None),
        ("E_HISTORY", "Did this unit hold setpoint in similar weather before?",
         {"undersized": "contradicts", "coil fouled": "supports"}, None),
    ],
    "AHU-SATDEV": [
        ("E_PLANT", "Is the chilled-water plant failing a supply or ΔT rule (CHW-1 / CHW-3 / DC-DT-1)?",
         {"CHW capacity": "supports"}, ("building_rule", ("CHW-1", "CHW-3", "DC-DT-1"), "fail")),
        ("E_HUNT", "Is the unit's control loop hunting (PID-HUNT-1)?",
         {"control loop": "supports"}, ("rule", ("PID-HUNT-1",), "fail")),
        ("E_FULL_CLG", "Is the supply air above setpoint even at full cooling (FC13)?",
         {"CHW capacity": "supports", "control loop": "contradicts"}, ("rule", ("FC13",), "fail")),
        ("E_LEAK", "Is a valve on this unit passing (FC14 / VLV-1)?",
         {"valve": "supports"}, ("rule", ("FC14", "VLV-1"), "fail")),
    ],
    "CHW-1": [
        ("E_PASSING", "Is any AHU in the building passing chilled water through a closed valve (FC14 / VLV-1)?",
         {"passing": "supports"}, ("building_rule", ("FC14", "VLV-1"), "fail")),
        ("E_CHWS_LOW", "Is chilled-water supply outside its setpoint band (CHW-3)?",
         {"setpoint": "supports"}, ("rule", ("CHW-3",), "fail")),
        ("E_BYPASS", "Is a decoupler / bypass line open or a 3-way valve in bypass?",
         {"decoupler": "supports", "3-way": "supports"}, None),
        ("E_PUMP_HIGH", "Are the pumps running near full speed while the loop DP is above setpoint?",
         {"over-pumping": "supports"}, None),
    ],
    "VAV-1": [
        ("E_AHU_WARM", "Is the parent AHU failing a supply-air rule (FC13 / AHU-SATDEV)?",
         {"AHU supply": "requires"}, ("parent_rule", ("FC13", "AHU-SATDEV"), "fail")),
        ("E_PINNED", "Is this box's damper pinned fully open (VAV-4)?",
         {"capacity": "supports", "stuck": "contradicts"}, ("rule", ("VAV-4",), "fail")),
        ("E_FLOW_BIAS", "Does the box report airflow with its damper closed (VAV-5)?",
         {"stuck": "supports"}, ("rule", ("VAV-5",), "fail")),
        ("E_SP_CHANGED", "Was the zone setpoint changed or put in override recently?",
         {"setpoint": "supports"}, None),
    ],
    "CMD-1": [
        ("E_VFD_FAULT", "Is the VFD / starter showing a fault or trip?", {"tripped": "supports"}, None),
        ("E_HOA", "Is the hand-off-auto switch in AUTO?", {"hand-off-auto": "excludes"}, None),
        ("E_CURRENT", "Does the fan draw normal current when commanded on?",
         {"status switch": "supports", "belt": "contradicts", "tripped": "excludes"}, None),
    ],
    "DC-DT-1": [
        ("E_BLDG_LOWDT", "Is the building-side loop also low ΔT (CHW-1)?",
         {"building-side": "requires"}, ("building_rule", ("CHW-1",), "fail")),
        ("E_ETS_VALVE", "Does the ETS control valve close fully at low load?",
         {"ETS control valve": "contradicts"}, None),
    ],
}

# Generic items asked for every rule.
_GENERIC: _Curated = [
    ("G_SENSOR", "Did a sensor used by this rule fail validation in the same window?",
     {"__spurious__": "supports", "sensor": "supports"}, ("sensor_invalid",)),
    ("G_PERSIST", "Is the fault present for most (≥ 50 %) of the running time?",
     {"__spurious__": "contradicts"}, ("fault_pct_ge", 50.0)),
    ("G_REPEAT", "Has this same fault been confirmed on this unit before?",
     {"__spurious__": "contradicts"}, ("previous_case",)),
]


def _links(keywords: Dict[str, str], hyps: List[Hypothesis]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for kw, strength in keywords.items():
        if kw == "__spurious__":
            out[SPURIOUS] = strength
            continue
        for h in hyps:
            if h.id != SPURIOUS and kw.lower() in h.label.lower():
                out[h.id] = strength
    return out


def default_kb(rule_id: str) -> RuleKB:
    rule = RULES_BY_ID[rule_id]
    hyps = [Hypothesis(SPURIOUS, _SPURIOUS_LABEL)] + [
        Hypothesis(f"H{i + 2}", label) for i, label in enumerate(rule.root_cause_candidates)]
    evidence = []
    for ev_id, q, kws, auto in _GENERIC + _CURATED.get(rule_id, []):
        links = _links(kws, hyps)
        if links:
            evidence.append(EvidenceItem(ev_id, q, links, auto))
    return RuleKB.seeded(rule_id, hyps, evidence)
