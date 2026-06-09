"""Verify commercial equipment dependency graph + cascade impact."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent_commercial.bms_data_model import Equipment, EquipmentType
from agent_commercial.topology import system_graph, impact_analysis


def _fleet():
    # CH-01 (chiller) feeds CHW-PUMP-01 → AHU-01, AHU-02 → VAV-01..02
    return [
        Equipment(equipment_id="CH-01", name="Chiller 1", equipment_type=EquipmentType.CHILLER,
                  child_equipment_ids=["CHWP-01"]),
        Equipment(equipment_id="CHWP-01", name="CHW Pump 1", equipment_type=EquipmentType.PUMP,
                  parent_equipment_id="CH-01", child_equipment_ids=["AHU-01", "AHU-02"]),
        Equipment(equipment_id="AHU-01", name="AHU 1", equipment_type=EquipmentType.AHU,
                  parent_equipment_id="CHWP-01", child_equipment_ids=["VAV-01"]),
        Equipment(equipment_id="AHU-02", name="AHU 2", equipment_type=EquipmentType.AHU,
                  parent_equipment_id="CHWP-01", child_equipment_ids=["VAV-02"]),
        Equipment(equipment_id="VAV-01", name="VAV 1", equipment_type=EquipmentType.VAV,
                  parent_equipment_id="AHU-01"),
        Equipment(equipment_id="VAV-02", name="VAV 2", equipment_type=EquipmentType.VAV,
                  parent_equipment_id="AHU-02"),
    ]


def main():
    fleet = _fleet()
    g = system_graph(fleet)
    assert len(g) == 6
    ch = next(n for n in g if n["equipment_id"] == "CH-01")
    assert ch["role"] == "generation" and ch["redundancy"] == "parallel"
    print("  graph:", {n['equipment_id']: f"{n['role']}/{n['redundancy']}" for n in g})

    # Chiller CRITICAL → major+ impact, downstream = pump + 2 AHUs + 2 VAVs (5 units)
    chiller_imp = impact_analysis(fleet, [("CH-01", "critical")])
    assert chiller_imp, "expected an impact"
    ci = chiller_imp[0]
    assert ci.equipment_id == "CH-01" and ci.impact in ("major", "critical")
    assert len(ci.downstream_affected) == 5, f"downstream={ci.downstream_affected}"
    print("  chiller-critical:", ci.impact, ci.system_impact,
          f"downstream={len(ci.downstream_affected)} building~-{ci.building_impact_pct}%")

    # VAV terminal MEDIUM → partial, no downstream, small building impact
    vav_imp = impact_analysis(fleet, [("VAV-01", "medium")])[0]
    assert vav_imp.impact == "partial" and len(vav_imp.downstream_affected) == 0
    print("  vav-medium:", vav_imp.impact, f"downstream={len(vav_imp.downstream_affected)}")

    # Ordering: chiller impact > vav impact
    both = impact_analysis(fleet, [("VAV-01", "medium"), ("CH-01", "critical")])
    assert both[0].equipment_id == "CH-01", "chiller should rank first"
    print("  ordering: chiller ranks above vav  ✅")

    print("\nRESULT: PASS — commercial dependency graph + cascade impact verified")


if __name__ == "__main__":
    main()
