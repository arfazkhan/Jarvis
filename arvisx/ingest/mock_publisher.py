"""
Mock device publisher — emits a community's signals to an MQTT broker so the full
ingest path (broker → MqttIngest → AssetStore → health/advisory) can be exercised
with no real hardware. Stands in for the future edge gateway.

Run (needs a broker on localhost:1883):
    python -m arvisx.ingest.mock_publisher --scenario prd
"""
from __future__ import annotations

import json
from typing import List

from arvisx.models import Asset
from arvisx.simulator import healthy_community, inject_prd_scenario


def asset_messages(asset: Asset, prefix: str = "arvisx") -> List[tuple[str, str]]:
    """All (topic, payload) messages for one asset's current footprint."""
    out: List[tuple[str, str]] = []
    base = f"{prefix}/{asset.asset_id}"
    out.append((f"{base}/runtime_hours", str(asset.runtime_hours)))
    out.append((f"{base}/online", "true" if asset.online else "false"))
    for k, v in (asset.signals or {}).items():
        payload = json.dumps(v) if isinstance(v, (dict, list)) else (
            v.isoformat() if hasattr(v, "isoformat") else str(v))
        out.append((f"{base}/{k}", payload))
    return out


def scenario_messages(scenario: str = "prd", prefix: str = "arvisx") -> List[tuple[str, str]]:
    assets = healthy_community() if scenario == "healthy" else inject_prd_scenario()
    msgs: List[tuple[str, str]] = []
    for a in assets:
        msgs.extend(asset_messages(a, prefix))
    return msgs


def _main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="prd", choices=["prd", "healthy"])
    ap.add_argument("--broker", default="localhost")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--prefix", default="arvisx")
    args = ap.parse_args()

    import paho.mqtt.client as mqtt
    c = mqtt.Client(client_id="arvisx-mock-pub")
    c.connect(args.broker, args.port, 60)
    msgs = scenario_messages(args.scenario, args.prefix)
    for topic, payload in msgs:
        c.publish(topic, payload, qos=1)
    c.disconnect()
    print(f"published {len(msgs)} messages for scenario '{args.scenario}' to {args.broker}:{args.port}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
