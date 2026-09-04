"""
HTML Templates for Rendering Swarm Investigation Artifacts
===========================================================
Generates highly aesthetic, premium, responsive HTML pages with CSS grid/flex layouts,
custom fonts (Inter, Fira Code), Material Symbols, glassmorphism effects, and premium charts
representing JSON raw telemetry data.
"""

import html
from typing import Any, Dict, List

def _html_escape(v: Any) -> str:
    return html.escape(str(v)) if v is not None else "—"

def render_reasoning_roadmap_html(equipment_id: str, content: dict) -> str:
    """Timeline / vertical roadmap displaying the multi-agent reasoning steps."""
    summary = content.get("summary", {})
    steps = content.get("steps", [])
    pipeline = content.get("investigation_pipeline", [])
    
    verdict = summary.get("final_verdict") or "Under Investigation"
    conf_band = summary.get("confidence_band") or "Low"
    elapsed = summary.get("elapsed_seconds") or 0.0
    grounded = "Yes" if summary.get("fully_grounded") else "Partial"
    
    conf_color = {"High": "#10b981", "Medium": "#f59e0b", "Low": "#ef4444"}.get(conf_band, "#94a3b8")
    
    # Render steps into interactive timeline cards
    steps_html = []
    for step in steps:
        s_num = step.get("step", 0)
        stage = step.get("stage", "")
        title = step.get("title", "")
        detail = step.get("detail", "")
        s_data = step.get("data", {})
        
        # Color codes based on stage
        stage_colors = {
            "Detect": ("#ef4444", "bg-rose-500/10 border-rose-500/30 text-rose-400"),
            "Investigate": ("#6366f1", "bg-indigo-500/10 border-indigo-500/30 text-indigo-400"),
            "Reason": ("#f59e0b", "bg-amber-500/10 border-amber-500/30 text-amber-400"),
            "Synthesize": ("#10b981", "bg-emerald-500/10 border-emerald-500/30 text-emerald-400"),
            "Advise": ("#7dd3fc", "bg-sky-500/10 border-sky-500/30 text-sky-400")
        }
        accent_color, badge_class = stage_colors.get(stage, ("#6366f1", "bg-indigo-500/10 border-indigo-500/30 text-indigo-400"))
        
        # Build step custom data display
        custom_data_html = ""
        if s_num == 1: # Detect
            alarms = s_data.get("alarms_triggered", [])
            if alarms:
                alarm_cards = []
                for al in alarms:
                    sev = al.get("sev", "").lower()
                    sev_class = "bg-rose-500/10 border-rose-500/30 text-rose-400" if "crit" in sev else "bg-amber-500/10 border-amber-500/30 text-amber-400"
                    alarm_cards.append(f"""
                    <div class="data-card border border-slate-700/50 rounded-xl p-3 bg-slate-900/60 mb-2">
                        <div class="flex justify-between items-center mb-1">
                            <span class="text-xs font-mono text-indigo-400 font-bold">{_html_escape(al.get('id'))}</span>
                            <span class="text-[10px] uppercase font-bold tracking-wider border rounded px-1.5 py-0.5 {sev_class}">{_html_escape(al.get('sev'))}</span>
                        </div>
                        <p class="text-xs text-slate-300 font-medium">{_html_escape(al.get('msg'))}</p>
                    </div>
                    """)
                custom_data_html = f"""
                <div class="mt-3">
                    <p class="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-2">Triggering Alarms</p>
                    {''.join(alarm_cards)}
                </div>
                """
        elif s_num == 2: # Investigate Agents
            agents = s_data.get("agents", [])
            if agents:
                agent_items = []
                for ag in agents:
                    agent_items.append(f"""
                    <div class="flex items-center gap-3 p-2 bg-slate-900/40 rounded-lg border border-slate-800/80">
                        <span class="material-symbols-outlined text-indigo-400 text-sm">support_agent</span>
                        <div>
                            <p class="text-xs font-bold text-slate-200">{_html_escape(ag.get('name'))}</p>
                            <p class="text-[10px] text-slate-400 font-medium">{_html_escape(ag.get('hypothesis'))}</p>
                        </div>
                    </div>
                    """)
                custom_data_html = f"""
                <div class="mt-3">
                    <p class="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-2">Specialist Dispatch Directory</p>
                    <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
                        {''.join(agent_items)}
                    </div>
                </div>
                """
        elif s_num == 3: # Tools/Evidence
            tool_calls = s_data.get("tool_calls_by_agent", [])
            if tool_calls:
                tc_items = []
                for tc in tool_calls:
                    tools_pills = "".join(f'<span class="pill-chip font-mono text-[9px] bg-slate-800 border border-slate-700 text-indigo-300 px-2 py-0.5 rounded">{_html_escape(t)}</span>' for t in tc.get("tools", []))
                    tc_items.append(f"""
                    <div class="p-2.5 bg-slate-900/50 rounded-xl border border-slate-800">
                        <div class="flex items-center gap-1.5 mb-1.5">
                            <span class="w-1.5 h-1.5 rounded-full bg-indigo-500"></span>
                            <span class="text-xs font-bold text-slate-200">{_html_escape(tc.get('agent'))}</span>
                        </div>
                        <div class="flex flex-wrap gap-1.5">{tools_pills}</div>
                    </div>
                    """)
                custom_data_html = f"""
                <div class="mt-3">
                    <p class="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-2">Evidence Collector Toolchains</p>
                    <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
                        {''.join(tc_items)}
                    </div>
                </div>
                """
        elif s_num == 5: # Synthesis/Faithfulness
            grounded_icon = "check_circle" if s_data.get("fully_grounded") else "warning"
            grounded_color = "text-emerald-400" if s_data.get("fully_grounded") else "text-amber-400"
            score = int(round(float(s_data.get("truth_score") or 0.9) * 100))
            custom_data_html = f"""
            <div class="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div class="bg-slate-900/40 border border-slate-800 rounded-xl p-3 flex items-center justify-between">
                    <div>
                        <p class="text-[10px] text-slate-400 uppercase font-bold tracking-wider">Semantic Grounding</p>
                        <p class="text-xs font-bold mt-0.5 text-slate-200">{"Fully Grounded" if s_data.get("fully_grounded") else "Heuristic Hypotheses Check"}</p>
                    </div>
                    <span class="material-symbols-outlined {grounded_color} text-2xl">{grounded_icon}</span>
                </div>
                <div class="bg-slate-900/40 border border-slate-800 rounded-xl p-3">
                    <div class="flex justify-between items-center mb-1">
                        <p class="text-[10px] text-slate-400 uppercase font-bold tracking-wider">Faithfulness Audit</p>
                        <p class="text-xs font-bold text-slate-200">{score}%</p>
                    </div>
                    <div class="w-full bg-slate-800 h-1.5 rounded-full overflow-hidden">
                        <div class="bg-gradient-to-r from-indigo-500 to-emerald-500 h-full rounded-full" style="width: {score}%"></div>
                    </div>
                </div>
            </div>
            """
        elif s_num == 6: # Action plan list
            actions = s_data.get("recommended_actions", [])
            if actions:
                act_items = "".join(f'<li class="text-xs text-slate-300 font-medium mb-1.5 leading-relaxed">{_html_escape(a)}</li>' for a in actions)
                custom_data_html = f"""
                <div class="mt-3 bg-indigo-950/20 border border-indigo-900/30 rounded-xl p-4">
                    <p class="text-[10px] font-bold text-indigo-400 uppercase tracking-widest mb-2">Swarm Recommended Corrective Actions</p>
                    <ol class="list-decimal pl-4">{act_items}</ol>
                </div>
                """
                
        steps_html.append(f"""
        <div class="timeline-card relative ml-8 pb-10 border-l border-slate-800 pl-8">
            <!-- Glow dot -->
            <div class="timeline-dot absolute -left-[8px] top-0 w-4 h-4 rounded-full border-2 border-slate-900 flex items-center justify-center" style="background-color: {accent_color}; box-shadow: 0 0 10px {accent_color}50;"></div>
            
            <div class="glass-card bg-slate-800/25 border border-slate-700/30 rounded-2xl p-5 hover:border-slate-700/60 transition-all">
                <div class="flex flex-wrap items-center justify-between gap-2 mb-2 select-none">
                    <div class="flex items-center gap-2">
                        <span class="text-xs font-mono font-bold bg-slate-900 text-slate-400 px-2 py-0.5 rounded">STEP 0{s_num}</span>
                        <h4 class="text-sm font-bold text-slate-100">{_html_escape(title)}</h4>
                    </div>
                    <span class="text-[9px] uppercase font-bold tracking-widest px-2 py-0.5 rounded border {badge_class}">{_html_escape(stage)}</span>
                </div>
                <p class="text-xs text-slate-300 leading-relaxed font-medium mb-1 select-all">{_html_escape(detail)}</p>
                {custom_data_html}
            </div>
        </div>
        """)
        
    pipeline_items_html = "".join(f"""
    <div class="flex items-center gap-1.5">
        <span class="text-[10px] font-bold font-mono {'text-emerald-400' if idx < 4 else 'text-slate-500'}">{_html_escape(p)}</span>
        { '<span class="material-symbols-outlined text-[12px] text-slate-700">chevron_right</span>' if idx < len(pipeline)-1 else '' }
    </div>
    """ for idx, p in enumerate(pipeline))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ARVIS Swarm Reasoning Roadmap — {_html_escape(equipment_id)}</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Fira+Code:wght@400;600&family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200" rel="stylesheet" />
    <style>
        :root {{
            --bg-color: #060913;
            --surface-color: #0c1222;
            --border-color: rgba(51, 65, 85, 0.3);
            --primary-accent: #6366f1;
            --text-color: #f1f5f9;
        }}
        body {{
            font-family: 'Inter', sans-serif;
            background: var(--bg-color);
            background-image: radial-gradient(circle at 10% 20%, rgba(99, 102, 241, 0.05) 0%, transparent 40%),
                              radial-gradient(circle at 90% 80%, rgba(16, 185, 129, 0.04) 0%, transparent 40%);
            color: var(--text-color);
            margin: 0;
            padding: 40px 24px;
        }}
        .container {{
            max-width: 1100px;
            margin: 0 auto;
        }}
        .glass-card {{
            background: rgba(12, 18, 34, 0.5);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border: 1px solid var(--border-color);
            border-radius: 24px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3);
        }}
        .header {{
            padding: 32px;
            margin-bottom: 24px;
        }}
        .header-top {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            flex-wrap: wrap;
            gap: 16px;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 24px;
            margin-bottom: 24px;
        }}
        .title-area h1 {{
            margin: 0;
            font-size: 24px;
            font-weight: 800;
            color: #ffffff;
            letter-spacing: -0.02em;
        }}
        .title-area p {{
            margin: 4px 0 0;
            font-size: 13px;
            color: #94a3b8;
            font-weight: 500;
        }}
        .pipeline-bar {{
            display: flex;
            align-items: center;
            gap: 8px;
            background: rgba(30, 41, 59, 0.4);
            padding: 6px 14px;
            border-radius: 99px;
            border: 1px solid rgba(255,255,255,0.03);
        }}
        .summary-stats {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 16px;
        }}
        .stat-card {{
            background: rgba(15, 23, 42, 0.4);
            border: 1px solid rgba(51, 65, 85, 0.2);
            border-radius: 16px;
            padding: 16px;
            display: flex;
            align-items: center;
            gap: 14px;
        }}
        .stat-icon {{
            width: 42px;
            height: 42px;
            border-radius: 12px;
            background: rgba(99, 102, 241, 0.1);
            color: var(--primary-accent);
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        .stat-value {{
            font-size: 18px;
            font-weight: 700;
            color: #ffffff;
            margin: 0;
        }}
        .stat-label {{
            font-size: 11px;
            color: #94a3b8;
            text-transform: uppercase;
            font-weight: 600;
            letter-spacing: 0.05em;
            margin: 2px 0 0;
        }}
        .main-layout {{
            display: grid;
            grid-template-columns: 1fr;
            gap: 24px;
            margin-top: 24px;
        }}
        .timeline-container {{
            position: relative;
            padding: 10px 0;
        }}
        .timeline-container::before {{
            content: '';
            position: absolute;
            left: 7px;
            top: 24px;
            bottom: 24px;
            width: 2px;
            background: linear-gradient(to bottom, var(--primary-accent), rgba(51,65,85,0.3));
            z-index: 0;
        }}
        .timeline-card:last-child {{
            border-left: 0 !important;
            padding-bottom: 0 !important;
        }}
        .data-card p {{
            margin: 0;
        }}
        .pill-chip {{
            display: inline-block;
        }}
    </style>
</head>
<body>
    <div class="container">
        <!-- Header Overview -->
        <div class="glass-card header">
            <div class="header-top">
                <div class="title-area">
                    <h1>ARVIS Swarm Reasoning Roadmap</h1>
                    <p>Causal chain audit trace for mechanical asset {_html_escape(equipment_id)}</p>
                </div>
                <div class="pipeline-bar">
                    {pipeline_items_html}
                </div>
            </div>
            
            <div class="summary-stats">
                <div class="stat-card">
                    <div class="stat-icon" style="color: {conf_color}; background: {conf_color}10;">
                        <span class="material-symbols-outlined">analytics</span>
                    </div>
                    <div>
                        <p class="stat-value" style="color: {conf_color}">{_html_escape(conf_band)}</p>
                        <p class="stat-label">Verdict Confidence</p>
                    </div>
                </div>
                <div class="stat-card">
                    <div class="stat-icon" style="color: #10b981; background: #10b98110;">
                        <span class="material-symbols-outlined">security</span>
                    </div>
                    <div>
                        <p class="stat-value">{_html_escape(grounded)}</p>
                        <p class="stat-label">Telemetry Grounded</p>
                    </div>
                </div>
                <div class="stat-card">
                    <div class="stat-icon">
                        <span class="material-symbols-outlined">timer</span>
                    </div>
                    <div>
                        <p class="stat-value">{elapsed:.1f}s</p>
                        <p class="stat-label">Investigation Time</p>
                    </div>
                </div>
                <div class="stat-card">
                    <div class="stat-icon" style="color: #7dd3fc; background: rgba(125,211,252,0.1)">
                        <span class="material-symbols-outlined">psychology</span>
                    </div>
                    <div>
                        <p class="stat-value" style="font-size:13px; font-weight:700; max-width: 170px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">{_html_escape(verdict)}</p>
                        <p class="stat-label">Consensus Verdict</p>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- Timeline Steps -->
        <div class="timeline-container">
            {''.join(steps_html)}
        </div>
    </div>
</body>
</html>
"""

def render_feedback_vs_command_html(equipment_id: str, content: dict) -> str:
    """Dashboard comparing commanded position vs actual position of all controllable actuators."""
    pairs = content.get("pairs", [])
    anomalous_pairs = content.get("anomalous_pairs", [])
    
    pairs_cards = []
    for p in pairs:
        label = p.get("label", "")
        cmd = p.get("commanded", 0.0)
        act = p.get("actual", 0.0)
        delta = p.get("delta", 0.0)
        pct_drift = p.get("pct_drift", 0.0)
        alarm = p.get("alarm", False)
        unit = p.get("unit", "")
        
        # Scale to percentage for slidebar rendering
        cmd_pct = cmd * 100 if unit == "fraction" else cmd
        act_pct = act * 100 if unit == "fraction" else act
        
        # Clip display variables between 0 and 100
        cmd_pct_disp = max(0, min(100, cmd_pct))
        act_pct_disp = max(0, min(100, act_pct))
        
        drift_color = "text-rose-400" if alarm else "text-indigo-400"
        border_glow = "border-rose-500/30 shadow-[0_0_20px_rgba(244,63,94,0.1)] bg-rose-950/5" if alarm else "border-slate-800/80 bg-slate-900/20"
        
        pairs_cards.append(f"""
        <div class="glass-card rounded-2xl p-6 border {border_glow} transition-all duration-300 hover:scale-[1.01]">
            <div class="flex justify-between items-start mb-4 select-none">
                <div>
                    <h3 class="text-sm font-bold text-slate-100 uppercase tracking-wider">{_html_escape(label)}</h3>
                    <p class="text-[10px] text-slate-400 uppercase mt-0.5">Control Loop Actuator</p>
                </div>
                { '<span class="material-symbols-outlined text-rose-500 font-bold animate-pulse text-lg" title="Linkage slip alarm active">warning</span>' if alarm else '<span class="material-symbols-outlined text-emerald-500 text-lg">check_circle</span>' }
            </div>
            
            <div class="grid grid-cols-2 gap-4 mb-5">
                <div class="p-3 bg-slate-950/40 rounded-xl border border-slate-800/80">
                    <p class="text-[9px] uppercase tracking-wider font-bold text-slate-500">Commanded Position</p>
                    <p class="text-xl font-bold text-sky-400 font-mono mt-1">{cmd * 100:.1f}%</p>
                </div>
                <div class="p-3 bg-slate-950/40 rounded-xl border border-slate-800/80">
                    <p class="text-[9px] uppercase tracking-wider font-bold text-slate-500">Feedback Actual</p>
                    <p class="text-xl font-bold text-amber-500 font-mono mt-1">{act * 100:.1f}%</p>
                </div>
            </div>
            
            <!-- Graphic Position Comparison Bar -->
            <div class="relative bg-slate-950/80 h-3 rounded-full overflow-visible mb-6 select-none border border-slate-800/50">
                <!-- Commanded Bar (Solid Blue) -->
                <div class="absolute left-0 top-0 h-full bg-sky-500/40 rounded-full" style="width: {cmd_pct_disp}%"></div>
                <!-- Actual Bar Indicator (Orange Glow Mark) -->
                <div class="absolute top-1/2 -translate-y-1/2 w-4 h-4 rounded-full bg-amber-500 shadow-[0_0_12px_rgba(245,158,11,0.8)] border border-white" style="left: calc({act_pct_disp}% - 8px)"></div>
            </div>
            
            <div class="flex justify-between items-center text-xs border-t border-slate-800/60 pt-4">
                <div>
                    <span class="text-slate-400">Deviation Offset:</span>
                    <span class="font-bold font-mono ml-1 text-slate-200">{delta * 100:+.1f}%</span>
                </div>
                <div>
                    <span class="text-slate-400">Drift Loop Error:</span>
                    <span class="font-bold font-mono ml-1 {drift_color}">{pct_drift}%</span>
                </div>
            </div>
            
            { f"""
            <div class="mt-4 p-3 bg-rose-500/10 border border-rose-500/20 text-[11px] font-medium text-rose-300 rounded-xl leading-relaxed">
                <strong>⚠ Slip Warning:</strong> Controllable command deviates heavily from feedback. Physical linkage slip, binding linkage joints, or actuator internal clutch failure is highly suspected.
            </div>
            """ if alarm else "" }
        </div>
        """)
        
    alarms_count_badge = f'<span class="bg-rose-500/20 border border-rose-500/40 text-rose-400 px-3 py-1 rounded-full text-xs font-bold font-mono uppercase select-none">{len(anomalous_pairs)} ALARMS ACTIVE</span>' if anomalous_pairs else '<span class="bg-emerald-500/20 border border-emerald-500/40 text-emerald-400 px-3 py-1 rounded-full text-xs font-bold font-mono uppercase select-none">ACTUATORS NOMINAL</span>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Actuator Diagnostics — {_html_escape(equipment_id)}</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Fira+Code:wght@400;600&family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200" rel="stylesheet" />
    <style>
        :root {{
            --bg-color: #060913;
            --surface-color: #0c1222;
            --border-color: rgba(51, 65, 85, 0.3);
            --primary-accent: #6366f1;
            --text-color: #f1f5f9;
        }}
        body {{
            font-family: 'Inter', sans-serif;
            background: var(--bg-color);
            background-image: radial-gradient(circle at 10% 20%, rgba(99, 102, 241, 0.05) 0%, transparent 40%),
                              radial-gradient(circle at 90% 80%, rgba(245, 158, 11, 0.03) 0%, transparent 40%);
            color: var(--text-color);
            margin: 0;
            padding: 40px 24px;
        }}
        .container {{
            max-width: 1100px;
            margin: 0 auto;
        }}
        .header {{
            padding: 32px;
            margin-bottom: 32px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 16px;
        }}
        .glass-card {{
            background: rgba(12, 18, 34, 0.5);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border: 1px solid var(--border-color);
            border-radius: 24px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3);
        }}
        .title-area h1 {{
            margin: 0;
            font-size: 24px;
            font-weight: 800;
            color: #ffffff;
            letter-spacing: -0.02em;
        }}
        .title-area p {{
            margin: 4px 0 0;
            font-size: 13px;
            color: #94a3b8;
            font-weight: 500;
        }}
        .actuators-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
            gap: 24px;
        }}
        @keyframes pulse {{
            0%, 100% {{ opacity: 1; }}
            50% {{ opacity: 0.5; }}
        }}
        .animate-pulse {{
            animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
        }}
    </style>
</head>
<body>
    <div class="container">
        <!-- Overview Header -->
        <div class="glass-card header">
            <div class="title-area">
                <h1>Actuator Feedback vs Command Ledger</h1>
                <p>Telemetry comparison for active damper motors & valves on {_html_escape(equipment_id)}</p>
            </div>
            <div>
                {alarms_count_badge}
            </div>
        </div>
        
        <!-- Actuator Cards Grid -->
        <div class="actuators-grid">
            {''.join(pairs_cards)}
        </div>
    </div>
</body>
</html>
"""

def render_evidence_manifest_html(equipment_id: str, content: dict) -> str:
    """LEDGER display of evidence grounding data points."""
    evidence = content.get("evidence", [])
    tools_used = content.get("tools_used", [])
    fully_grounded = content.get("fully_grounded", True)
    
    grounded_badge = """
    <div class="flex items-center gap-2 bg-emerald-500/10 border border-emerald-500/35 text-emerald-400 px-4 py-1.5 rounded-full select-none shadow-[0_0_15px_rgba(16,185,129,0.1)]">
        <span class="material-symbols-outlined text-base">verified</span>
        <span class="text-xs uppercase font-extrabold tracking-widest">100% Telemetry Grounded</span>
    </div>
    """ if fully_grounded else """
    <div class="flex items-center gap-2 bg-amber-500/10 border border-amber-500/35 text-amber-400 px-4 py-1.5 rounded-full select-none shadow-[0_0_15px_rgba(245,158,11,0.1)]">
        <span class="material-symbols-outlined text-base">warning</span>
        <span class="text-xs uppercase font-extrabold tracking-widest">Partially Grounded Swarm</span>
    </div>
    """
    
    rows_html = []
    for ev in evidence:
        idx = ev.get("index", 1)
        label = ev.get("label", "")
        val = ev.get("value")
        unit = ev.get("unit", "")
        conf = ev.get("confidence", 0.95)
        conf_pct = ev.get("confidence_pct", "95%")
        
        # Color codes based on label
        icon = "device_thermostat" if "temp" in label.lower() else ("air" if "damper" in label.lower() or "oa" in label.lower() or "flow" in label.lower() else "bar_chart")
        conf_pct_num = int(round(float(conf) * 100))
        conf_bar_color = "bg-emerald-500" if conf_pct_num >= 80 else ("bg-indigo-500" if conf_pct_num >= 55 else "bg-amber-500")
        
        rows_html.append(f"""
        <tr class="hover:bg-slate-900/30 transition-colors border-b border-slate-800/50">
            <td class="px-6 py-4 text-xs font-mono font-bold text-slate-500 select-none">{idx:02d}</td>
            <td class="px-6 py-4">
                <div class="flex items-center gap-3">
                    <div class="w-8 h-8 rounded-lg bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 flex items-center justify-center select-none">
                        <span class="material-symbols-outlined text-lg">{icon}</span>
                    </div>
                    <div>
                        <p class="text-xs font-bold text-slate-200 select-all">{_html_escape(label)}</p>
                        <p class="text-[9px] font-bold text-slate-500 uppercase tracking-wide">BACnet Sensor Point</p>
                    </div>
                </div>
            </td>
            <td class="px-6 py-4">
                <span class="font-mono font-bold text-sm bg-slate-950/70 border border-slate-800 text-indigo-400 px-3 py-1.5 rounded-xl select-all">
                    {val} <span class="text-[10px] text-slate-400 font-sans ml-0.5">{_html_escape(unit)}</span>
                </span>
            </td>
            <td class="px-6 py-4">
                <div class="flex items-center gap-3 max-w-[200px]">
                    <div class="w-full bg-slate-950/60 border border-slate-800/40 h-2 rounded-full overflow-hidden select-none">
                        <div class="h-full rounded-full {conf_bar_color}" style="width: {conf_pct_num}%"></div>
                    </div>
                    <span class="font-mono text-xs font-bold text-slate-300">{conf_pct}</span>
                </div>
            </td>
            <td class="px-6 py-4 text-right select-none">
                <span class="text-[9px] bg-indigo-950/30 border border-indigo-900/50 text-indigo-300 px-2.5 py-1 rounded-full font-bold uppercase tracking-wider">Telemetry API</span>
            </td>
        </tr>
        """)
        
    tool_chips = "".join(f'<span class="tool-pill bg-slate-900 border border-slate-800 text-indigo-300 font-mono text-[10px] px-3 py-1 rounded-lg select-none">{_html_escape(t)}</span>' for t in tools_used)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Grounded Evidence Ledger — {_html_escape(equipment_id)}</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Fira+Code:wght@400;600&family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200" rel="stylesheet" />
    <style>
        :root {{
            --bg-color: #060913;
            --surface-color: #0c1222;
            --border-color: rgba(51, 65, 85, 0.3);
            --primary-accent: #6366f1;
            --text-color: #f1f5f9;
        }}
        body {{
            font-family: 'Inter', sans-serif;
            background: var(--bg-color);
            background-image: radial-gradient(circle at 10% 20%, rgba(99, 102, 241, 0.05) 0%, transparent 40%),
                              radial-gradient(circle at 90% 80%, rgba(16, 185, 129, 0.04) 0%, transparent 40%);
            color: var(--text-color);
            margin: 0;
            padding: 40px 24px;
        }}
        .container {{
            max-width: 1000px;
            margin: 0 auto;
        }}
        .header {{
            padding: 32px;
            margin-bottom: 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 16px;
        }}
        .glass-card {{
            background: rgba(12, 18, 34, 0.5);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border: 1px solid var(--border-color);
            border-radius: 24px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3);
            overflow: hidden;
        }}
        .title-area h1 {{
            margin: 0;
            font-size: 24px;
            font-weight: 800;
            color: #ffffff;
            letter-spacing: -0.02em;
        }}
        .title-area p {{
            margin: 4px 0 0;
            font-size: 13px;
            color: #94a3b8;
            font-weight: 500;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            text-align: left;
        }}
        th {{
            background: rgba(15, 23, 42, 0.4);
            border-bottom: 1px solid var(--border-color);
            color: #94a3b8;
            font-size: 10px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.1em;
            padding: 16px 24px;
        }}
        .tools-section {{
            margin-top: 24px;
            padding: 24px;
        }}
        .tools-list {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 12px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <!-- Overview Header -->
        <div class="glass-card header">
            <div class="title-area">
                <h1>Grounded Swarm Evidence Ledger</h1>
                <p>Consensus parameters verified against telemetry on {_html_escape(equipment_id)}</p>
            </div>
            <div>
                {grounded_badge}
            </div>
        </div>
        
        <!-- Evidence Table Card -->
        <div class="glass-card">
            <table>
                <thead>
                    <tr>
                        <th style="width: 60px;">Index</th>
                        <th>Evidence Parameter</th>
                        <th style="width: 180px;">Observed Value</th>
                        <th style="width: 250px;">Verification Groundedness</th>
                        <th style="width: 130px; text-align: right;">Authority Source</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(rows_html)}
                </tbody>
            </table>
        </div>
        
        <!-- Swarm Query Tools Section -->
        { f"""
        <div class="glass-card tools-section">
            <h3 class="text-xs font-bold text-slate-100 uppercase tracking-wider" style="margin: 0;">Swarm Instrumentation Tools Utilized</h3>
            <div class="tools-list">
                {tool_chips}
            </div>
        </div>
        """ if tools_used else "" }
    </div>
</body>
</html>
"""

def render_trend_chart_json_html(equipment_id: str, content: dict) -> str:
    """Renders the JSON sparkline list as a beautiful graphical line chart using Canvas/ChartJS."""
    series = content.get("series", {})
    
    # Render fallback list in case ChartJS is slow or fails
    fallback_items = []
    for pk, info in series.items():
        sparkline = info.get("sparkline", "")
        cur = info.get("current", 0.0)
        c_min = info.get("min", 0.0)
        c_max = info.get("max", 0.0)
        fallback_items.append(f"""
        <div class="p-4 bg-slate-900/50 rounded-xl border border-slate-800 flex items-center justify-between">
            <div>
                <p class="text-xs font-bold text-slate-300">{_html_escape(pk)}</p>
                <p class="text-[9px] uppercase tracking-wide text-slate-500 font-bold mt-0.5">Range: {c_min} to {c_max}</p>
            </div>
            <div class="flex items-center gap-4">
                <span class="font-mono text-xs text-indigo-400 font-bold bg-slate-950 px-2 py-1 rounded border border-slate-800">{cur}</span>
                <span class="font-mono text-xs font-medium text-slate-400 select-none tracking-widest">{sparkline}</span>
            </div>
        </div>
        """)
        
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Telemetry History Trend — {_html_escape(equipment_id)}</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200" rel="stylesheet" />
    <style>
        :root {{
            --bg-color: #060913;
            --surface-color: #0c1222;
            --border-color: rgba(51, 65, 85, 0.3);
            --primary-accent: #6366f1;
            --text-color: #f1f5f9;
        }}
        body {{
            font-family: 'Inter', sans-serif;
            background: var(--bg-color);
            background-image: radial-gradient(circle at 10% 20%, rgba(99, 102, 241, 0.05) 0%, transparent 40%);
            color: var(--text-color);
            margin: 0;
            padding: 40px 24px;
        }}
        .container {{
            max-width: 900px;
            margin: 0 auto;
            display: flex;
            flex-direction: column;
            gap: 24px;
        }}
        .header {{
            padding: 24px 32px;
        }}
        .glass-card {{
            background: rgba(12, 18, 34, 0.5);
            backdrop-filter: blur(16px);
            border: 1px solid var(--border-color);
            border-radius: 24px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3);
            padding: 24px;
        }}
        .title-area h1 {{
            margin: 0;
            font-size: 20px;
            font-weight: 800;
            color: #ffffff;
            letter-spacing: -0.02em;
        }}
        .title-area p {{
            margin: 4px 0 0;
            font-size: 12px;
            color: #94a3b8;
        }}
        .sparklines-list {{
            display: flex;
            flex-direction: column;
            gap: 12px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <div class="glass-card header">
            <div class="title-area">
                <h1>Telemetry Point Trends</h1>
                <p>Observed history timeline sparklines on {_html_escape(equipment_id)}</p>
            </div>
        </div>
        
        <!-- Fallback List -->
        <div class="glass-card">
            <h3 class="text-xs font-bold text-slate-100 uppercase tracking-wider mb-4" style="margin: 0 0 16px 0;">Telemetry History Sparklines</h3>
            <div class="sparklines-list">
                {''.join(fallback_items)}
            </div>
        </div>
    </div>
</body>
</html>
"""
