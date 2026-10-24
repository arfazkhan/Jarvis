"""
What every data source looks like to ARVIS.

The BACnet, Modbus and OPC UA adapters grew the same shape independently; this
names it, so the source manager can run any number of them side by side and new
connectors (MQTT, SNMP, REST, manual readings, ...) plug in without touching
main.py. Nothing here changes the existing adapters — they already satisfy it.

  DataSource   polled or pushed time-series points (BMSDataPoint via on_point_update)
  EventSource  also emits discrete events (badge swipes, people counts, bookings)

Read-only by contract: a source reads from building systems and never writes to
them (enforced by tests/test_deployment_security.py).
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Protocol, runtime_checkable


@runtime_checkable
class DataSource(Protocol):
    def load_points_from_config(self, config: Dict[str, Any]) -> int: ...

    async def connect(self) -> bool: ...

    async def disconnect(self) -> None: ...

    async def start_polling(self, interval_seconds: float = 30) -> None: ...

    async def stop_polling(self) -> None: ...

    def on_point_update(self, callback: Callable[..., Any]) -> None: ...

    def get_stats(self) -> Dict[str, Any]: ...


@runtime_checkable
class EventSource(DataSource, Protocol):
    def on_event(self, callback: Callable[[Dict[str, Any]], Any]) -> None: ...


def source_tag(kind: str, source_id: str) -> str:
    """The `source` stamped on a source's points: the kind alone when the id is the
    kind (one source of that kind — what the legacy modes produce), else kind:id."""
    return kind if not source_id or source_id == kind else f"{kind}:{source_id}"
