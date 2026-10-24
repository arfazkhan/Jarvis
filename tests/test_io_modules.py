"""
Phase 1 — the cheap rungs: Modbus RTU over RS-485, and Modbus I/O modules wired to
equipment that speaks no protocol at all (dry contacts, 4-20 mA, pulse outputs).

Real: the templates in config/templates/io_modules, the expansion, the Modbus
adapter's register decoding and scaling. Scripted: the serial/TCP client (the wire).
"""
import asyncio

import pytest

from agent_commercial import modbus_adapter as mb
from agent_commercial.io_modules import expand


def test_dry_contacts_become_status_points():
    regs = expand([{"template": "digital_inputs", "unit_id": 3, "channels": {
        0: {"point_id": "LIFT-1/FAULT", "equipment_id": "LIFT-1", "role": "fault-status"},
        2: {"point_id": "FP-1/RUN", "equipment_id": "FP-1"}}}])
    assert [(r["point_id"], r["register_type"], r["address"], r["unit_id"]) for r in regs] == \
        [("LIFT-1/FAULT", "discrete", 0, 3), ("FP-1/RUN", "discrete", 2, 3)]
    assert regs[0]["role"] == "fault-status"


def test_4_20ma_maps_raw_counts_onto_the_transmitters_range():
    (reg,) = expand([{"template": "analog_4_20ma", "unit_id": 4, "raw_range": [4000, 20000], "channels": {
        1: {"point_id": "TANK-1/LVL", "equipment_id": "TANK-1", "unit": "%", "range": [0, 100]}}}])
    point = mb._point_from_config(reg, 1)
    assert reg["address"] == 1 and reg["register_type"] == "input"
    assert point.apply_scaling(4000) == pytest.approx(0.0)       # 4 mA  → empty
    assert point.apply_scaling(12000) == pytest.approx(50.0)     # 12 mA → half
    assert point.apply_scaling(20000) == pytest.approx(100.0)    # 20 mA → full
    with pytest.raises(ValueError, match="needs range"):
        expand([{"template": "analog_4_20ma", "channels": {0: {"point_id": "X/Y"}}}])


def test_pulse_counters_are_32_bit_and_scaled_per_pulse():
    regs = expand([{"template": "pulse_counters", "channels": {
        0: {"point_id": "WM-1/TOTAL", "unit": "m3", "per_pulse": 0.01},
        1: {"point_id": "GM-1/TOTAL", "unit": "m3", "per_pulse": 0.1}}}])
    assert [(r["address"], r["data_type"], r["scale"]) for r in regs] == [(0, "uint32", 0.01), (2, "uint32", 0.1)]


def test_template_fields_can_be_overridden_and_unknown_templates_are_named():
    (reg,) = expand([{"template": "digital_inputs", "address_base": 100, "register_type": "coil",
                      "channels": {5: {"point_id": "SUMP-1/HIGH"}}}])
    assert (reg["address"], reg["register_type"]) == (105, "coil")
    with pytest.raises(ValueError, match="unknown I/O module template 'adam9999'.*digital_inputs"):
        expand([{"template": "adam9999", "channels": {}}])


def test_the_adapter_loads_io_modules_alongside_registers():
    ad = mb.ModbusAdapter(host="10.0.0.9")
    n = ad.load_points_from_config({"registers": [{"register_type": "holding", "address": 3000, "point_id": "MTR-1/KW",
                                                   "data_type": "float32", "unit": "kW"}],
                                    "io_modules": [{"template": "digital_inputs", "channels": {
                                        0: {"point_id": "GEN-1/RUN", "equipment_id": "GEN-1"}}}]})
    assert n == 2 and set(ad._points) == {"MTR-1/KW", "GEN-1/RUN"}


# ── Modbus RTU (RS-485) ──────────────────────────────────────────────────────
class _Client:
    made = []

    def __init__(self, **kw):
        self.kw = kw
        _Client.made.append(self)

    async def connect(self):
        return True

    def close(self):
        pass


def test_rtu_opens_the_serial_line(monkeypatch):
    monkeypatch.setattr(mb, "PYMODBUS_AVAILABLE", True)
    monkeypatch.setattr(mb, "AsyncModbusSerialClient", type("Serial", (_Client,), {}), raising=False)
    monkeypatch.setattr(mb, "AsyncModbusTcpClient", type("Tcp", (_Client,), {}), raising=False)
    ad = mb.modbus_adapter_from_config({"transport": "rtu", "serial_port": "/dev/ttyUSB0", "baudrate": 19200,
                                        "parity": "e", "unit_id": 7})
    assert asyncio.run(ad.connect()) is True
    client = _Client.made[-1]
    assert type(client).__name__ == "Serial"
    assert client.kw == {"port": "/dev/ttyUSB0", "baudrate": 19200, "parity": "E", "stopbits": 1, "bytesize": 8,
                         "timeout": 5.0}
    assert ad._where() == "RTU /dev/ttyUSB0 19200 8E1"
    tcp = mb.modbus_adapter_from_config({"host": "10.0.0.20"})
    asyncio.run(tcp.connect())
    assert type(_Client.made[-1]).__name__ == "Tcp"


def test_rtu_without_a_serial_port_is_refused():
    with pytest.raises(ValueError, match="needs serial_port"):
        mb.ModbusAdapter(transport="rtu")
    with pytest.raises(ValueError, match="tcp or rtu"):
        mb.ModbusAdapter(host="x", transport="ascii")


def test_io_module_roles_reach_the_role_registry():
    from types import SimpleNamespace
    from agent_commercial.bms_state_engine import BMSStateEngine
    from agent_commercial.main import OpsCopilot
    ns = SimpleNamespace(state_engine=BMSStateEngine(), bacnet_config={}, opcua_config={}, sources_config=[],
                         modbus_config={"io_modules": [{"template": "analog_4_20ma", "channels": {
                             0: {"point_id": "CHWP-1/DP", "role": "chw-dp", "unit": "kPa",
                                 "range": [0, 250]}}}]})
    ns._config_point_entries = lambda: OpsCopilot._config_point_entries(ns)
    assert OpsCopilot._register_config_roles(ns) == 1
