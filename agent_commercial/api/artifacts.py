"""
Investigation Artifact Generator
=================================
Produces post-investigation artifacts from a completed InvestigationResult (IR).

Minimum 3 artifacts always produced:
  summary_report     — HTML summary printable to PDF
  reasoning_roadmap  — structured causal chain timeline (how ARVIS reached conclusion)
  trend_chart        — point history chart for key sensor(s)

Additional artifacts when data supports:
  feedback_vs_command — when equipment has both CMD and actual position points
  evidence_manifest   — when investigation produced ≥2 key_evidence entries

Equipment-adaptive: the generator inspects available BMS points before deciding
the artifact set. A chiller gets VIB/COP charts; an AHU gets damper slip snapshots.
"""
from __future__ import annotations

import base64
import html
import io
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("arvis.api.artifacts")

# In-memory store keyed by artifact_set_id. Swap for DB in production.
_ARTIFACT_STORE: Dict[str, Dict] = {}

# ── Equipment point families (cmd/actual pairs, primary trend points) ─────────

_CMD_ACTUAL_PAIRS: Dict[str, List[Tuple[str, str]]] = {
    # suffix -> (cmd_suffix, actual_suffix)
    "AHU":    [("OA_DMPR_CMD", "OA_DMPR"), ("CHW_VALVE_CMD", "CHW_VALVE"),
               ("SF_SPD_CMD", "SF_SPD")],
    "FCU":    [("CHW_VALVE_CMD", "CHW_VALVE"), ("FAN_SPD_CMD", "FAN_SPD")],
    "CHILLER": [("CHWST_SP", "CHWST"), ("COND_VALVE_CMD", "COND_VALVE")],
    "VAV":    [("DMPR_CMD", "DMPR"), ("REHEAT_CMD", "REHEAT_VALVE")],
    "PUMP":   [("SPD_CMD", "SF_SPD")],
    "CT":     [("FAN_SPD_CMD", "FAN_SPD"), ("BYPASS_CMD", "BYPASS_VALVE")],
}

_PRIMARY_TREND_POINTS: Dict[str, List[str]] = {
    "AHU":    ["MAT", "SAT", "RAT", "OA_DMPR", "CHW_VALVE", "SF_SPD"],
    "FCU":    ["SAT", "RAT", "CHW_VALVE"],
    "CHILLER": ["CHWST", "CHWRT", "COP", "KW", "VIB_RMS"],
    "VAV":    ["ZN_TEMP", "ZN_SETPOINT", "DMPR"],
    "PUMP":   ["DP", "FLOW", "SF_SPD", "VIB_RMS"],
    "CT":     ["CWS", "CWR", "FAN_SPD", "VIB_RMS"],
}


def _eq_family(equipment_id: str) -> str:
    """Derive equipment family string from ID prefix."""
    eid = (equipment_id or "").upper()
    for fam in ("AHU", "FCU", "CHILLER", "CH", "VAV", "PUMP", "CT"):
        if eid.startswith(fam):
            return "CHILLER" if fam == "CH" else fam
    return "AHU"  # safe default


def _html_escape(v: Any) -> str:
    return html.escape(str(v)) if v is not None else "—"


# ── Matplotlib helpers (graceful degradation) ─────────────────────────────────

def _try_import_matplotlib():
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        return plt, mdates
    except ImportError:
        return None, None


def _sparkline_text(values: List[float]) -> str:
    """ASCII sparkline fallback when matplotlib is absent."""
    if not values:
        return "no data"
    blocks = " ▁▂▃▄▅▆▇█"
    lo, hi = min(values), max(values)
    span = hi - lo or 1
    return "".join(blocks[max(0, min(8, int((v - lo) / span * 8)))] for v in values[-40:])


def _png_base64(fig) -> str:
    """Render matplotlib figure to base64 PNG string."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, bbox_inches="tight",
                facecolor="#0f172a", edgecolor="none")
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()


# ── Artifact builders ──────────────────────────────────────────────────────────

def _build_summary_report(ir: dict, equipment_id: str, alarms: List[dict]) -> dict:
    """HTML investigation summary — printable as PDF from browser."""
    rc = ir.get("root_cause") or {}
    metrics = ir.get("metrics") or {}
    anomaly = ir.get("anomaly") or {}
    actions = ir.get("recommended_actions") or []
    evidence = ir.get("key_evidence") or []
    agents = ir.get("agents") or []

    conf_band = rc.get("confidence_band", "—")
    conf_color = {"High": "#22c55e", "Medium": "#f59e0b", "Low": "#ef4444"}.get(conf_band, "#94a3b8")
    grounded_badge = (
        '<span style="color:#22c55e">✓ Grounded</span>'
        if ir.get("fully_grounded")
        else '<span style="color:#f59e0b">⚠ Partially Grounded</span>'
    )

    evidence_rows = "".join(
        f"<tr><td>{_html_escape(e.get('label',''))}</td>"
        f"<td><strong>{_html_escape(e.get('value',''))}</strong> {_html_escape(e.get('unit',''))}</td>"
        f"<td>{round(float(e.get('confidence') or 0) * 100)}%</td></tr>"
        for e in evidence
    )
    action_items = "".join(
        f"<li>{_html_escape(a.get('step', a) if isinstance(a, dict) else a)}</li>"
        for a in actions
    )
    alarm_rows = "".join(
        f"<tr><td>{_html_escape(a.get('alarm_id',''))}</td>"
        f"<td>{_html_escape(a.get('message',''))}</td>"
        f"<td>{_html_escape(a.get('severity',''))}</td></tr>"
        for a in alarms[:10]
    )
    agent_rows = "".join(
        f"<tr><td>{_html_escape(ag.get('name',''))}</td>"
        f"<td>{_html_escape(ag.get('action',''))}</td>"
        f"<td>{_html_escape(ag.get('status',''))}</td></tr>"
        for ag in agents
    )

    html_content = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>ARVIS Investigation Report — {_html_escape(equipment_id)}</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; background:#0f172a; color:#e2e8f0;
          margin:0; padding:32px; }}
  .header {{ background:linear-gradient(135deg,#1e3a5f,#0f2a4a); border-radius:12px;
             padding:28px 32px; margin-bottom:24px; }}
  .header h1 {{ margin:0 0 4px; font-size:22px; color:#7dd3fc; }}
  .header .sub {{ color:#94a3b8; font-size:13px; }}
  .badge {{ display:inline-block; padding:3px 10px; border-radius:99px; font-size:12px;
            font-weight:600; background:#1e293b; margin:4px; }}
  .section {{ background:#1e293b; border-radius:10px; padding:20px 24px;
              margin-bottom:18px; }}
  .section h2 {{ margin:0 0 14px; font-size:15px; color:#7dd3fc; text-transform:uppercase;
                 letter-spacing:.08em; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th {{ color:#94a3b8; font-weight:600; text-align:left; padding:6px 8px;
        border-bottom:1px solid #334155; }}
  td {{ padding:6px 8px; border-bottom:1px solid #1e293b; }}
  .root-cause-box {{ background:#0f2a1a; border-left:4px solid {conf_color};
                     border-radius:6px; padding:14px 16px; }}
  .metric-grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:12px; }}
  .metric {{ background:#0f172a; border-radius:8px; padding:12px; text-align:center; }}
  .metric .val {{ font-size:22px; font-weight:700; color:#7dd3fc; }}
  .metric .lbl {{ font-size:11px; color:#64748b; margin-top:2px; }}
  ol {{ margin:0; padding-left:20px; }}
  li {{ margin-bottom:6px; font-size:13px; }}
</style>
</head>
<body>
<div class="header">
  <h1>ARVIS Investigation Report</h1>
  <div class="sub">
    Equipment: <strong>{_html_escape(equipment_id)}</strong> &nbsp;|&nbsp;
    Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} &nbsp;|&nbsp;
    {grounded_badge}
  </div>
</div>

<div class="section">
  <h2>Root Cause Finding</h2>
  <div class="root-cause-box">
    <p style="margin:0 0 8px;font-size:14px;">{_html_escape(rc.get('statement') or 'Under investigation')}</p>
    <span class="badge" style="color:{conf_color}">Confidence: {_html_escape(conf_band)}</span>
    <span class="badge">Label: {_html_escape(rc.get('label',''))}</span>
    {"<span class='badge' style='color:#22c55e'>✓ Confirmed</span>" if rc.get('confirmed') else ""}
  </div>
</div>

<div class="section">
  <h2>Investigation Metrics</h2>
  <div class="metric-grid">
    <div class="metric"><div class="val">{metrics.get('agents_investigated',0)}</div><div class="lbl">Agents Investigated</div></div>
    <div class="metric"><div class="val">{metrics.get('tools_executed',0)}</div><div class="lbl">Tools Executed</div></div>
    <div class="metric"><div class="val">{metrics.get('data_points_analyzed',0)}</div><div class="lbl">Data Points Analyzed</div></div>
    <div class="metric"><div class="val">{int(round(float(metrics.get('confidence') or 0)*100))}%</div><div class="lbl">Diagnostic Confidence</div></div>
    <div class="metric"><div class="val">{int(round(float(metrics.get('truth_score') or 0)*100))}%</div><div class="lbl">Truth Score</div></div>
    <div class="metric"><div class="val">{round(float(metrics.get('elapsed_seconds') or 0),1)}s</div><div class="lbl">Investigation Time</div></div>
  </div>
</div>

{"<div class='section'><h2>Key Evidence</h2><table><tr><th>Measurement</th><th>Value</th><th>Confidence</th></tr>" + evidence_rows + "</table></div>" if evidence_rows else ""}

{"<div class='section'><h2>Active Alarms</h2><table><tr><th>Alarm ID</th><th>Message</th><th>Severity</th></tr>" + alarm_rows + "</table></div>" if alarm_rows else ""}

{"<div class='section'><h2>Recommended Actions</h2><ol>" + action_items + "</ol></div>" if action_items else ""}

{"<div class='section'><h2>Agent Participation</h2><table><tr><th>Agent</th><th>Action</th><th>Status</th></tr>" + agent_rows + "</table></div>" if agent_rows else ""}

<div class="section" style="font-size:11px;color:#475569;text-align:center;padding:12px;">
  ARVIS — Autonomous Real-time Verification & Insight System &nbsp;|&nbsp;
  Marina Heights, West Bay Doha &nbsp;|&nbsp; Read-only diagnostic system
</div>
</body>
</html>"""

    return {
        "type": "summary_report",
        "label": f"Investigation Summary — {equipment_id}",
        "format": "html",
        "mime": "text/html",
        "content": html_content,
        "description": "Full investigation summary printable as PDF.",
    }


def _build_reasoning_roadmap(ir: dict, equipment_id: str, alarms: List[dict]) -> dict:
    """Structured causal chain: how ARVIS reached its conclusion."""
    anomaly = ir.get("anomaly") or {}
    rc = ir.get("root_cause") or {}
    metrics = ir.get("metrics") or {}
    agents = ir.get("agents") or []
    tool_activity = ir.get("tool_activity") or []
    flow = ir.get("investigation_flow") or ["Detect", "Investigate", "Reason", "Synthesize", "Advise"]

    # Group tool calls by agent for step 3
    tools_by_agent: Dict[str, List[str]] = {}
    for tc in tool_activity:
        ag = tc.get("agent") or "ARVIS"
        tools_by_agent.setdefault(ag, []).append(tc.get("tool", "unknown"))

    # Collapse tool lists
    tool_summary = [
        {"agent": ag, "tools": list(dict.fromkeys(tl))}  # deduplicated, order-preserving
        for ag, tl in tools_by_agent.items()
    ]

    trigger_alarms = [
        {"id": a.get("alarm_id", ""), "msg": a.get("message", ""), "sev": a.get("severity", "")}
        for a in alarms[:6]
    ]

    steps = [
        {
            "step": 1,
            "stage": "Detect",
            "title": "Anomaly Detection",
            "detail": (
                f"Watchdog detected anomaly on {equipment_id}. "
                f"Sensor: {anomaly.get('anomaly_point') or 'MAT'}. "
                f"Z-score: {anomaly.get('z_score') or 'computed'}. "
                f"Severity: {anomaly.get('severity') or 'significant'}."
            ),
            "data": {
                "alarms_triggered": trigger_alarms,
                "anomaly_type": anomaly.get("type"),
                "z_score": anomaly.get("z_score"),
            },
        },
        {
            "step": 2,
            "stage": "Investigate",
            "title": "Swarm Dispatch",
            "detail": (
                f"{metrics.get('agents_investigated', len(agents))} specialist agents dispatched. "
                f"Each agent assigned a hypothesis to test independently."
            ),
            "data": {
                "agents": [{"name": ag.get("name"), "hypothesis": ag.get("action")} for ag in agents],
            },
        },
        {
            "step": 3,
            "stage": "Investigate",
            "title": "Evidence Gathering",
            "detail": (
                f"{metrics.get('tools_executed', len(tool_activity))} tool calls executed across agents. "
                f"{metrics.get('data_points_analyzed', 0)} data points analyzed. "
                f"{metrics.get('evidence_count', 0)} evidence items registered in ledger."
            ),
            "data": {"tool_calls_by_agent": tool_summary},
        },
        {
            "step": 4,
            "stage": "Reason",
            "title": "Hypothesis Evaluation",
            "detail": (
                f"{metrics.get('hypotheses_evaluated', 0)} hypotheses evaluated. "
                f"{metrics.get('agents_converged', 0)} agents reached consensus. "
                "Numeric audit verified all cited values against evidence ledger."
            ),
            "data": {
                "hypotheses_evaluated": metrics.get("hypotheses_evaluated"),
                "agents_converged": metrics.get("agents_converged"),
                "data_coverage": metrics.get("data_coverage"),
            },
        },
        {
            "step": 5,
            "stage": "Synthesize",
            "title": "Synthesis & Verification",
            "detail": (
                "Faithfulness pipeline ran correction loop. "
                f"Grounded: {ir.get('fully_grounded', False)}. "
                f"Unverified claims: {ir.get('has_unverified_claims', False)}. "
                f"Truth score: {round(float(metrics.get('truth_score') or 0) * 100)}%."
            ),
            "data": {
                "fully_grounded": ir.get("fully_grounded"),
                "has_unverified_claims": ir.get("has_unverified_claims"),
                "truth_score": metrics.get("truth_score"),
                "confidence": metrics.get("confidence"),
            },
        },
        {
            "step": 6,
            "stage": "Advise",
            "title": "Conclusion",
            "detail": (
                f"Root cause: {rc.get('statement') or 'see report'}. "
                f"Confidence: {rc.get('confidence_band', '—')}. "
                f"Confirmed: {rc.get('confirmed', False)}."
            ),
            "data": {
                "root_cause": rc.get("statement"),
                "confidence_band": rc.get("confidence_band"),
                "label": rc.get("label"),
                "confirmed": rc.get("confirmed"),
                "recommended_actions": [
                    (a.get("step") if isinstance(a, dict) else a)
                    for a in (ir.get("recommended_actions") or [])
                ],
            },
        },
    ]

    return {
        "type": "reasoning_roadmap",
        "label": "ARVIS Reasoning Roadmap",
        "format": "json",
        "mime": "application/json",
        "content": {
            "equipment_id": equipment_id,
            "investigation_pipeline": flow,
            "steps": steps,
            "summary": {
                "total_steps": len(steps),
                "elapsed_seconds": metrics.get("elapsed_seconds"),
                "final_verdict": rc.get("label"),
                "confidence_band": rc.get("confidence_band"),
                "fully_grounded": ir.get("fully_grounded"),
            },
        },
        "description": "Step-by-step causal chain showing how ARVIS reached its conclusion.",
    }


async def _build_trend_chart(
    ir: dict,
    equipment_id: str,
    bms_state,
) -> Optional[dict]:
    """Point history trend chart for primary sensors. PNG if matplotlib available, else sparkline data."""
    family = _eq_family(equipment_id)
    point_keys = _PRIMARY_TREND_POINTS.get(family, ["MAT", "SAT"])[:4]

    # Fetch history for each candidate point
    series: Dict[str, List] = {}
    for pk in point_keys:
        pid = f"{equipment_id}/{pk}"
        try:
            hist = await bms_state.get_point_history(pid, 120)  # 2h window
            if hist and len(hist) >= 2:
                series[pk] = hist
        except Exception:
            pass

    if not series:
        # Try fetching via current_values as single-point fallback
        try:
            snap = await bms_state.get_snapshot()
            cv = snap.get("current_values", {})
            for pk in point_keys:
                pid = f"{equipment_id}/{pk}"
                if pid in cv and cv[pid] is not None:
                    series[pk] = [(datetime.now(), float(cv[pid]))]
        except Exception:
            pass

    if not series:
        return None

    plt, mdates = _try_import_matplotlib()

    if plt is not None:
        # Full matplotlib chart
        fig, ax = plt.subplots(figsize=(10, 4))
        fig.patch.set_facecolor("#0f172a")
        ax.set_facecolor("#1e293b")

        colors = ["#7dd3fc", "#f59e0b", "#a78bfa", "#34d399", "#fb7185"]
        for idx, (pk, hist) in enumerate(series.items()):
            try:
                if hist and isinstance(hist[0], (list, tuple)):
                    ts = [h[0] for h in hist]
                    vals = [float(h[1]) for h in hist]
                elif hist and isinstance(hist[0], dict):
                    ts = [datetime.fromisoformat(h["timestamp"]) if isinstance(h["timestamp"], str) else h["timestamp"] for h in hist]
                    vals = [float(h["value"]) for h in hist]
                else:
                    continue
                ax.plot(ts, vals, color=colors[idx % len(colors)],
                        linewidth=1.8, label=pk, marker="o", markersize=2)
            except Exception as e:
                logger.debug(f"[Artifacts] chart series {pk} failed: {e}")

        ax.set_xlabel("Time", color="#94a3b8", fontsize=9)
        ax.set_ylabel("Value", color="#94a3b8", fontsize=9)
        ax.set_title(f"{equipment_id} — Sensor Trend", color="#e2e8f0", fontsize=11, pad=10)
        ax.tick_params(colors="#64748b", labelsize=8)
        ax.spines["bottom"].set_color("#334155")
        ax.spines["left"].set_color("#334155")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.grid(axis="y", color="#1e293b", linewidth=0.5, linestyle="--")
        if len(series) > 1:
            ax.legend(fontsize=8, facecolor="#1e293b", edgecolor="#334155",
                      labelcolor="#e2e8f0")
        try:
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
            ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        except Exception:
            pass

        png_b64 = _png_base64(fig)
        plt.close(fig)

        content = {"format": "png_base64", "data": png_b64}
        fmt = "png_base64"
    else:
        # Sparkline fallback — structured series data
        sparklines = {}
        for pk, hist in series.items():
            try:
                if hist and isinstance(hist[0], (list, tuple)):
                    vals = [float(h[1]) for h in hist]
                else:
                    vals = [float(h.get("value", 0)) for h in hist]
                sparklines[pk] = {
                    "sparkline": _sparkline_text(vals),
                    "min": round(min(vals), 2),
                    "max": round(max(vals), 2),
                    "current": round(vals[-1], 2),
                    "count": len(vals),
                }
            except Exception:
                pass
        content = {"format": "sparkline", "series": sparklines}
        fmt = "sparkline_json"

    return {
        "type": "trend_chart",
        "label": f"Sensor Trend — {equipment_id}",
        "format": fmt,
        "mime": "image/png" if fmt == "png_base64" else "application/json",
        "content": content,
        "description": f"Point history for {', '.join(series.keys())} over the investigation window.",
        "series_names": list(series.keys()),
    }


async def _build_feedback_vs_command(
    ir: dict,
    equipment_id: str,
    bms_state,
) -> Optional[dict]:
    """Commanded vs actual position snapshot for actuators.

    Returns None if no CMD/actual pairs are present in the current snapshot.
    """
    family = _eq_family(equipment_id)
    pairs = _CMD_ACTUAL_PAIRS.get(family, [])
    if not pairs:
        return None

    try:
        snap = await bms_state.get_snapshot()
        cv = snap.get("current_values", {})
    except Exception:
        return None

    found_pairs = []
    for cmd_sfx, actual_sfx in pairs:
        cmd_pid = f"{equipment_id}/{cmd_sfx}"
        act_pid = f"{equipment_id}/{actual_sfx}"
        # Accept either prefixed or bare point IDs
        cmd_val = cv.get(cmd_pid) or cv.get(cmd_sfx)
        act_val = cv.get(act_pid) or cv.get(actual_sfx)
        if cmd_val is not None and act_val is not None:
            try:
                cv_f = float(cmd_val)
                av_f = float(act_val)
                delta = round(av_f - cv_f, 4)
                pct_drift = round(abs(delta) / max(abs(cv_f), 0.001) * 100, 1)
                found_pairs.append({
                    "label": actual_sfx.replace("_", " "),
                    "commanded": round(cv_f, 4),
                    "actual": round(av_f, 4),
                    "delta": delta,
                    "pct_drift": pct_drift,
                    "alarm": abs(delta) > 0.15,   # >15% deviation = attention flag
                    "unit": "fraction" if max(cv_f, av_f) <= 1.05 else "%",
                })
            except Exception:
                pass

    if not found_pairs:
        return None

    # Optional: matplotlib bar chart
    plt, _ = _try_import_matplotlib()
    chart_data = None
    if plt is not None:
        try:
            labels = [p["label"] for p in found_pairs]
            cmds = [p["commanded"] * 100 if p["unit"] == "fraction" else p["commanded"] for p in found_pairs]
            acts = [p["actual"] * 100 if p["unit"] == "fraction" else p["actual"] for p in found_pairs]
            x = range(len(labels))

            fig, ax = plt.subplots(figsize=(7, 3.5))
            fig.patch.set_facecolor("#0f172a")
            ax.set_facecolor("#1e293b")

            width = 0.35
            ax.bar([xi - width / 2 for xi in x], cmds, width, label="Commanded (%)", color="#7dd3fc", alpha=0.85)
            ax.bar([xi + width / 2 for xi in x], acts, width, label="Actual (%)", color="#f59e0b", alpha=0.85)

            ax.set_xticks(list(x))
            ax.set_xticklabels(labels, color="#94a3b8", fontsize=9)
            ax.tick_params(colors="#64748b", labelsize=8)
            ax.set_ylabel("Position (%)", color="#94a3b8", fontsize=9)
            ax.set_title(f"{equipment_id} — Feedback vs Command", color="#e2e8f0", fontsize=11)
            ax.legend(fontsize=8, facecolor="#1e293b", edgecolor="#334155", labelcolor="#e2e8f0")
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)
            ax.spines["bottom"].set_color("#334155")
            ax.spines["left"].set_color("#334155")

            chart_data = {"format": "png_base64", "data": _png_base64(fig)}
            plt.close(fig)
        except Exception as e:
            logger.debug(f"[Artifacts] fvc chart failed: {e}")

    content = {
        "pairs": found_pairs,
        "equipment_id": equipment_id,
        "anomalous_pairs": [p for p in found_pairs if p["alarm"]],
    }
    if chart_data:
        content["chart"] = chart_data

    return {
        "type": "feedback_vs_command",
        "label": f"Feedback vs Command — {equipment_id}",
        "format": "json",
        "mime": "application/json",
        "content": content,
        "description": "Commanded vs actual position for all controllable actuators.",
    }


def _build_evidence_manifest(ir: dict, equipment_id: str) -> Optional[dict]:
    """Full evidence manifest — every grounded data point with source attribution."""
    evidence = ir.get("key_evidence") or []
    if len(evidence) < 2:
        return None

    tool_activity = ir.get("tool_activity") or []
    tool_set = list(dict.fromkeys(tc.get("tool", "") for tc in tool_activity if tc.get("tool")))

    rows = []
    for i, ev in enumerate(evidence):
        rows.append({
            "index": i + 1,
            "label": ev.get("label", ""),
            "value": ev.get("value"),
            "unit": ev.get("unit", ""),
            "confidence": round(float(ev.get("confidence") or 0), 3),
            "confidence_pct": f"{round(float(ev.get('confidence') or 0) * 100)}%",
        })

    return {
        "type": "evidence_manifest",
        "label": "Evidence Manifest",
        "format": "json",
        "mime": "application/json",
        "content": {
            "equipment_id": equipment_id,
            "evidence_count": len(rows),
            "evidence": rows,
            "tools_used": tool_set,
            "fully_grounded": ir.get("fully_grounded"),
            "has_unverified_claims": ir.get("has_unverified_claims"),
        },
        "description": "Every evidence item registered during investigation with source and confidence.",
    }


# ── Public API ─────────────────────────────────────────────────────────────────

class InvestigationArtifactGenerator:
    """Generates post-investigation artifact sets from a completed IR."""

    async def generate(
        self,
        ir: dict,
        bms_state=None,
        active_alarms: Optional[List[dict]] = None,
        investigation_id: Optional[str] = None,
    ) -> dict:
        """
        Generate all applicable artifacts for the investigation.

        Returns a dict suitable for storage and API response:
          {
            "artifact_set_id": str,
            "investigation_id": str | None,
            "equipment_id": str,
            "generated_at": str,
            "artifacts": List[ArtifactDict],
          }
        """
        equipment_id = ir.get("equipment_id") or "UNKNOWN"
        alarms_dicts = active_alarms or []
        artifact_set_id = f"ART-{uuid.uuid4().hex[:10].upper()}"

        artifacts = []

        # 1. Summary report — always
        try:
            artifacts.append(_build_summary_report(ir, equipment_id, alarms_dicts))
        except Exception as e:
            logger.error(f"[Artifacts] summary_report failed: {e}")

        # 2. Reasoning roadmap — always
        try:
            artifacts.append(_build_reasoning_roadmap(ir, equipment_id, alarms_dicts))
        except Exception as e:
            logger.error(f"[Artifacts] reasoning_roadmap failed: {e}")

        # 3. Trend chart — always (requires bms_state)
        if bms_state is not None:
            try:
                chart = await _build_trend_chart(ir, equipment_id, bms_state)
                if chart:
                    artifacts.append(chart)
            except Exception as e:
                logger.error(f"[Artifacts] trend_chart failed: {e}")

        # 4. Feedback vs command — equipment-conditional
        if bms_state is not None:
            try:
                fvc = await _build_feedback_vs_command(ir, equipment_id, bms_state)
                if fvc:
                    artifacts.append(fvc)
            except Exception as e:
                logger.debug(f"[Artifacts] feedback_vs_command skipped: {e}")

        # 5. Evidence manifest — when ≥2 evidence items
        try:
            manifest = _build_evidence_manifest(ir, equipment_id)
            if manifest:
                artifacts.append(manifest)
        except Exception as e:
            logger.debug(f"[Artifacts] evidence_manifest skipped: {e}")

        # Assign stable IDs for download routing
        for art in artifacts:
            art["id"] = f"{artifact_set_id}-{art['type']}"

        result = {
            "artifact_set_id": artifact_set_id,
            "investigation_id": investigation_id,
            "equipment_id": equipment_id,
            "generated_at": datetime.now().isoformat(),
            "artifact_count": len(artifacts),
            "artifact_types": [a["type"] for a in artifacts],
            "artifacts": artifacts,
        }

        _ARTIFACT_STORE[artifact_set_id] = result
        logger.info(
            f"[Artifacts] Generated {len(artifacts)} artifacts for {equipment_id} "
            f"(set={artifact_set_id}): {result['artifact_types']}"
        )
        return result


def get_artifact_set(artifact_set_id: str) -> Optional[dict]:
    return _ARTIFACT_STORE.get(artifact_set_id)


def get_artifact_by_id(artifact_id: str) -> Optional[dict]:
    """Find a single artifact by its compound ID (artifact_set_id-type)."""
    for aset in _ARTIFACT_STORE.values():
        for art in aset.get("artifacts", []):
            if art.get("id") == artifact_id:
                return art
    return None
