"""
Dumb equipment, connected for the price of a Modbus I/O module.

A lift with only a "fault" relay, a fire pump with a "running" contact, a tank
with a 4-20 mA level transmitter, a water meter with a pulse output: none of them
speak a protocol, but a small Modbus I/O box wired to them does. Instead of
working out register addresses and scaling by hand, a site config names the
module's template and what is wired to each channel:

    modbus:                                   # or a `sources:` entry of kind modbus
      io_modules:
        - template: digital_inputs
          unit_id: 3
          channels:
            0: {point_id: LIFT-1/FAULT, equipment_id: LIFT-1, role: fault-status}
            1: {point_id: FP-1/RUN,     equipment_id: FP-1,   role: run-status}
        - template: analog_4_20ma
          unit_id: 4
          raw_range: [0, 65535]               # this module's counts at 4 and 20 mA
          channels:
            0: {point_id: TANK-1/LVL, equipment_id: TANK-1, unit: "%", range: [0, 100]}
        - template: pulse_counters
          unit_id: 5
          channels:
            0: {point_id: WM-1/TOTAL, equipment_id: WM-1, unit: m3, per_pulse: 0.01}

`expand()` turns that into ordinary register entries (same shape as
`modbus.registers`), so the adapter, roles and alarms treat them like any point.
Templates live in config/templates/io_modules/*.yaml; any template field can be
overridden per module (address_base, raw_range, register_type, ...).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "config" / "templates" / "io_modules"
_TEMPLATE_KEYS = ("kind", "register_type", "data_type", "address_base", "address_step", "raw_range")


def load_template(name: str, directory: Optional[Path] = None) -> Dict[str, Any]:
    import yaml
    path = (directory or TEMPLATE_DIR) / f"{name}.yaml"
    if not path.exists():
        known = sorted(p.stem for p in (directory or TEMPLATE_DIR).glob("*.yaml"))
        raise ValueError(f"unknown I/O module template {name!r} (known: {', '.join(known)})")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def expand(modules: List[Dict[str, Any]], directory: Optional[Path] = None) -> List[Dict[str, Any]]:
    """io_modules entries → Modbus register entries."""
    out: List[Dict[str, Any]] = []
    for i, mod in enumerate(modules or []):
        if not isinstance(mod, dict) or not mod.get("template"):
            raise ValueError(f"io_modules[{i}] needs a template")
        t = {**load_template(mod["template"], directory), **{k: mod[k] for k in _TEMPLATE_KEYS if k in mod}}
        kind = t.get("kind")
        base, step = int(t.get("address_base", 0)), int(t.get("address_step", 1))
        for ch, wired in (mod.get("channels") or {}).items():
            if not isinstance(wired, dict) or not wired.get("point_id"):
                raise ValueError(f"io_modules[{i}] channel {ch} needs a point_id")
            reg = {k: v for k, v in wired.items() if k not in ("range", "per_pulse")}
            reg.update(register_type=t["register_type"], data_type=t.get("data_type", "uint16"),
                       address=base + int(ch) * step)
            if "unit_id" in mod:
                reg["unit_id"] = mod["unit_id"]
            if kind == "analog":
                lo, hi = (wired.get("range") or [None, None])
                if lo is None or hi is None:
                    raise ValueError(f"{wired['point_id']}: an analog channel needs range: [low, high] "
                                     "(what its transmitter reads at 4 and 20 mA)")
                raw_lo, raw_hi = t.get("raw_range") or [4000, 20000]
                scale = (float(hi) - float(lo)) / (float(raw_hi) - float(raw_lo))
                reg.update(scale=scale, offset=float(lo) - float(raw_lo) * scale)
            elif kind == "counter":
                reg["scale"] = float(wired.get("per_pulse", 1.0))
            out.append(reg)
    return out
