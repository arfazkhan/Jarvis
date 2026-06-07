"""Tests for the agent tool registry — extensibility + the domain tools return real data."""
from __future__ import annotations

from arvisx.learning import BaselineStore
from arvisx.simulator import community_zones, healthy_community
from arvisx.store import AssetStore
from arvisx.tools import REGISTRY
from arvisx.workorders import WorkOrderStore


def _ctx():
    assets = healthy_community()
    bl = BaselineStore()
    for _ in range(25):
        bl.learn_from_assets(assets)
    store = AssetStore.from_fleet_definition(healthy_community())
    return {"by_id": {a.asset_id: a for a in assets}, "assets": assets, "risks": [],
            "db": None, "baselines": bl, "skillbook": None, "store": store,
            "zones": community_zones("prd"), "wo_store": WorkOrderStore()}


def test_registry_schemas_and_doc():
    names = REGISTRY.names()
    # the original 6 + the domain expansion
    for core in ("get_asset_state", "get_baseline", "check_dependency_impact", "get_active_risks"):
        assert core in names
    for new in ("get_water_status", "get_cost_estimate", "get_community_readiness",
                "get_virtual_sensors", "get_fusion_findings", "get_signal_quality",
                "get_stale_signals", "get_zone_occupancy", "get_work_orders"):
        assert new in names, f"missing domain tool {new}"
    assert len(names) >= 15
    schemas = REGISTRY.schemas()
    assert all(s["type"] == "function" and "name" in s["function"] for s in schemas)
    assert "get_water_status()" in REGISTRY.doc()


def test_unknown_tool_and_bad_args_are_safe():
    ctx = _ctx()
    assert "error" in REGISTRY.call("nope", ctx, {})
    # tools never raise — bad args return an error dict, not an exception
    assert isinstance(REGISTRY.call("get_baseline", ctx, {"asset_id": "X"}), dict)


def test_domain_tools_return_real_data():
    ctx = _ctx()
    w = REGISTRY.call("get_water_status", ctx, {})
    assert w["stored_l"] > 0 and "band" in w

    rd = REGISTRY.call("get_community_readiness", ctx, {})
    assert 0 <= rd["readiness"] <= 100 and rd["services"]

    vs = REGISTRY.call("get_virtual_sensors", ctx, {"asset_id": "BOOST-PUMP-01"})
    assert vs["asset_id"] == "BOOST-PUMP-01" and "virtual" in vs

    state = REGISTRY.call("get_asset_state", ctx, {"asset_id": "GEN-01"})
    assert state["type"] == "diesel_generator"


def test_add_a_tool_at_runtime():
    """Demonstrates extensibility: a new capability is one decorator."""
    @REGISTRY.register("ping_test", "demo tool", {"type": "object", "properties": {}})
    def _ping(ctx, **_):
        return {"pong": True}

    assert "ping_test" in REGISTRY.names()
    assert REGISTRY.call("ping_test", _ctx(), {}) == {"pong": True}


if __name__ == "__main__":
    test_registry_schemas_and_doc()
    test_unknown_tool_and_bad_args_are_safe()
    test_domain_tools_return_real_data()
    test_add_a_tool_at_runtime()
    print(f"PASS — registry + {len(REGISTRY.names())} tools verified")
