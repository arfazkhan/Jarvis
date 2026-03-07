# UI Mapping Guide: Swarm & Interactive Demo

This guide explains how to map background swarm events and simulation states to specific UI components for a production-grade interactive demo.

## 1. Ambient Thinking (Background Monitoring)
Shows the building's autonomous monitoring even when not "acting".

- **Event Type**: [thought](file:///e:/Automation/tests/omega_stress_test/omega_test_runner.py#2219-2251) (via SSE).
- **Source**: [QueenCoordinator](file:///e:/Automation/arvis_core/swarm/queen.py#17-301) background loops.
- **UI Component**: A fading "Neural Activity" ticker or a "Pulse" indicator.
- **Message Logic**: Filter for "Monitoring", "Stabilizing", or "Analyzing" prefixes.

## 2. Swarm Conflict (BFT Debate)
Visualizes the internal debate between specialized agents.

- **Event Type**: `swarm_event`.
- **Payload**: `{"agent": "Comfort", "action": "VETO", "reason": "Occupant safety breach"}`.
- **UI Component**: A "Swarm War Room" view with cards for each active agent (Energy, Comfort, Strategic). Highlight VETO actions in red.

## 3. Truth-Score Gauge (Grounding)
A real-time indicator of how well the AI's "hallucinated" projections match the "real" building sensors.

- **Event Type**: `truth_score`.
- **UI Component**: A circular gauge (0-100%).
- **State mapping**:
    - **95-100%**: SOLID (Verified)
    - **80-94%**: DRIFT (Warning)
    - **<80%**: UNSAFE (Withheld)

## 4. Interactive Simulation Control
Maps manual UI actions to simulation injections.

| UI Action | API Call | Sim Impact |
| :--- | :--- | :--- |
| **Fault Switch** | `POST /sim/inject` | Trips equipment (e.g. Chiller vibration ramp). |
| **Accept Advisory** | `POST /advisories/{id}/acknowledge` | Executes the swarm's proposed fix in the physics engine. |
| **Speed Slider** | `POST /sim/control` | Adjusts how many simulation hours pass per real-time minute. |
