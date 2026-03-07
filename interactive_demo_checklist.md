# ARVIS Interactive Demo Verification Checklist

This checklist ensures the **Vertical Cognitive Loop** is functioning correctly across the hardware-accelerated K2 backend and your frontend UI.

## 🛡️ 1. Initialization & Connectivity
- [ ] **Handshake**: Start the backend and verify the UI connects to `http://localhost:8000/api/v1/demo/status`. Ensure `is_running: true` is displayed.
- [ ] **Asset Registration**: Call `POST /api/v1/demo/initialize-building`. Verify that the equipment list (AHU-01, CHILLER-01, etc.) appears in your telemetry panel.
- [ ] **Clock Sync**: Verify that the "Simulation Time" in the UI progresses (e.g., 1 sim-minute every real second).

## 🌡️ 2. Real-Time Physics (Telemetry)
- [ ] **Baseline Drift**: Watch a "Healthy" AHU in the UI. Its `Supply Air Temp` should hold steady around 19°C.
- [ ] **Micro-vibrations**: Ensure the Chiller's vibration metric is fluctuating slightly (±0.05 mm/s) rather than staying static.
- [ ] **Load Scaling**: Verify that as the outdoor temperature rises, the Chiller's **KW Load** increases in the UI charts.

## 🧪 3. Scenario Management (Chaos Test)
- [ ] **Direct Injection**: Use the Scenario Manager to inject a `CHILLER_VIBRATION` fault (value: `5.8`). 
- [ ] **UI Reaction**: Verify that the specific equipment card in the UI highlights in **Red/Alert** state within 3 seconds.
- [ ] **State Transition**: Verify the backend `agent_state` switches from `MONITORING` to `ANALYZING`.

## 🧠 4. Glass Box Reasoning (SSE Stream)
- [ ] **Real-time Thoughts**: Subscribe to `GET /api/v1/stream/thoughts`. Verify that raw logic from the Strategic Agent starts scrolling in the console/terminal.
- [ ] **K2 Specifics**: Confirm you see the reasoning blocks (e.g., "Analyzing vibration surge on CHILLER-01...") being streamed in real-time.
- [ ] **Tool Use Visibility**: Verify the UI displays when an agent "calls a tool" (e.g., `Executing: list_equipment`).

## 🤝 5. Human-in-the-Loop (Decision Hub)
- [ ] **Simulation Pause**: When consensus is reached, verify the simulation enters the `INTERVENING` state (clock freezes).
- [ ] **Consensus View**: Verify the UI displays the **Multi-Option Advisory** with agent voting results.
- [ ] **Acknowledgment**: Click **[ACCEPT]** in the UI. Verify that:
    - [ ] Request sent to `/api/v1/demo/advisory/{id}/respond`.
    - [ ] UI alert clears and vibration resets to normal.

## 🎯 6. Truth-Score & Resilience
- [ ] **Truth Gauge**: Intentionally ignore an alert. Verify the **Truth-Score Gauge** in the UI drops accordingly.
- [ ] **Fallback Test**: Under heavy load, verify logs show `[UnifiedLLM]` automatically failing back to Groq without UI interruption.
