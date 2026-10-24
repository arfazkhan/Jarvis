"""
History from any BMS: trend exports (CSV / XLSX) → ARVIS's telemetry.

Every BMS can export trend logs. Importing them gives a building months of
history on day one — what "normal" looks like (thresholds, baselines, the 28-day
learning) without waiting four weeks.

Two shapes are understood:

  wide   timestamp, AHU-01/SAT, AHU-01/RAT, ...     (one column per point)
  long   timestamp, point_id, value[, unit]          (one row per reading)

`columns` renames export headers to ARVIS point ids ({"AHU-01 Supply Air Temp (°C)":
"AHU-01/SAT"}); unmapped wide columns keep their header as the point id. The
timezone of the export must be stated (tz="Asia/Qatar", or "local" for this box):
exports rarely say, and guessing would shift every reading by hours.

Imported readings go straight into history (source "import") — never through the
live state engine — so old values can't raise alarms or replace current ones.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

_TS_NAMES = ("timestamp", "time", "date_time", "datetime", "date", "ts")
_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%m/%d/%Y %H:%M:%S",
            "%m/%d/%Y %I:%M:%S %p", "%d-%b-%Y %H:%M:%S", "%Y/%m/%d %H:%M:%S")


def _zone(tz: str):
    if not tz:
        raise ValueError("say which timezone the export is in (tz='Asia/Qatar', or 'local' for this box)")
    if tz == "local":
        return None
    from zoneinfo import ZoneInfo
    return ZoneInfo(tz)


def _parse_ts(raw: Any, zone) -> Optional[datetime]:
    if isinstance(raw, datetime):
        dt = raw
    else:
        s = str(raw or "").strip()
        if not s:
            return None
        dt = None
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            for fmt in _FORMATS:
                try:
                    dt = datetime.strptime(s, fmt)
                    break
                except ValueError:
                    continue
        if dt is None:
            return None
    if dt.tzinfo is None and zone is not None:
        dt = dt.replace(tzinfo=zone)
    return dt                                     # aware → stored on this host's clock by to_storage_ts


def _rows_from_xlsx(data: bytes) -> List[List[Any]]:
    try:
        import openpyxl
    except ImportError as e:
        raise ValueError("XLSX needs openpyxl (pip install openpyxl) — or export the trend as CSV") from e
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    return [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)]


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v or "").strip().replace(",", "")
    if s.lower() in ("on", "true", "active"):
        return 1.0
    if s.lower() in ("off", "false", "inactive"):
        return 0.0
    try:
        f = float(s)
        return f if f == f else None
    except ValueError:
        return None


async def import_trends(database: Any, data: Any, *, tz: str, columns: Optional[Dict[str, str]] = None,
                        units: Optional[Dict[str, str]] = None, filename: str = "", batch: int = 5000) -> Dict[str, Any]:
    """Import a trend export. `data` is CSV text or XLSX bytes. Returns counts and what was skipped."""
    zone = _zone(tz)
    columns, units = columns or {}, units or {}
    if isinstance(data, (bytes, bytearray)) and (filename.lower().endswith(".xlsx") or data[:2] == b"PK"):
        table = _rows_from_xlsx(bytes(data))
    else:
        text = data.decode("utf-8-sig", errors="replace") if isinstance(data, (bytes, bytearray)) else str(data)
        table = list(csv.reader(io.StringIO(text)))
    if not table:
        raise ValueError("the export is empty")
    header = [str(h or "").strip() for h in table[0]]
    lower = [h.lower() for h in header]
    ts_col = next((i for i, h in enumerate(lower) if h in _TS_NAMES), None)
    if ts_col is None:
        raise ValueError(f"no timestamp column (looked for {', '.join(_TS_NAMES)})")
    long_form = "point_id" in lower and "value" in lower

    def readings() -> Iterable[Dict[str, Any]]:
        for row in table[1:]:
            if not row or ts_col >= len(row):
                continue
            ts = _parse_ts(row[ts_col], zone)
            if ts is None:
                stats["bad_timestamps"] += 1
                continue
            if long_form:
                pid = str(row[lower.index("point_id")] or "").strip()
                v = _num(row[lower.index("value")])
                unit = str(row[lower.index("unit")]).strip() if "unit" in lower and row[lower.index("unit")] else ""
                cells = [(columns.get(pid, pid), v, unit or units.get(pid, ""))]
            else:
                cells = [(columns.get(header[i], header[i]), _num(row[i]), units.get(header[i], ""))
                         for i in range(len(header)) if i != ts_col and i < len(row) and header[i]]
            for pid, v, unit in cells:
                if not pid:
                    continue
                if v is None:
                    stats["non_numeric"] += 1
                    continue
                yield {"point_id": pid, "equipment_id": pid.split("/")[0], "value": v, "unit": unit,
                       "quality": "good", "timestamp": ts, "source": "import", "confidence": 1.0}

    stats = {"rows": 0, "points": 0, "bad_timestamps": 0, "non_numeric": 0, "first": None, "last": None}
    seen, buf = set(), []
    for r in readings():
        buf.append(r)
        seen.add(r["point_id"])
        stats["first"] = min(stats["first"] or r["timestamp"], r["timestamp"]) if stats["first"] else r["timestamp"]
        stats["last"] = max(stats["last"] or r["timestamp"], r["timestamp"])
        if len(buf) >= batch:
            await database.save_data_points_batch(buf)
            stats["rows"] += len(buf)
            buf = []
    if buf:
        await database.save_data_points_batch(buf)
        stats["rows"] += len(buf)
    stats["points"] = len(seen)
    stats["first"] = stats["first"].isoformat() if stats["first"] else None
    stats["last"] = stats["last"].isoformat() if stats["last"] else None
    return stats
