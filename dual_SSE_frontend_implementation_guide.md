# ARVIS Frontend Integration Guide (Master)

This document provides the definitive technical specification for integrating the ARVIS "Glass Box" UI. It covers the dual-channel SSE streams, the dynamic task checklist system, and the response parsing logic required for production-grade deployment.

---

## 1. Dual-Channel Architecture

ARVIS separates high-volume background analysis from user-specific interactions to ensure UI performance and state isolation.

### Endpoints
1.  **`/api/v1/stream/monitor` (Global)**: Connect at the app root. Broadcasts overarching building intelligence (ambient thoughts, passive telemetry, high-level advisories).
2.  **`/api/v1/stream/chat` (Session-Based)**: Connect only when the chat sidebar is active. Broadcasts user-specific reasoning, tool calls, and swarm task lists.

### Implementation Strategy
```javascript
// Global Monitor Hook (App-wide)
const useArvisMonitor = () => {
  useEffect(() => {
    const sse = new EventSource('/api/v1/stream/monitor');
    sse.addEventListener('thought', (e) => showAmbientHint(JSON.parse(e.data).content));
    return () => sse.close();
  }, []);
};

// Chat Sidebar Hook (Component-level)
const useArvisChat = (sessionId) => {
  const [tasks, setTasks] = useState([]);
  const [logs, setLogs] = useState([]);

  useEffect(() => {
    const sse = new EventSource('/api/v1/stream/chat');
    
    // Swarm Pipeline Progress
    sse.addEventListener('task_list', (e) => setTasks(JSON.parse(e.data).tasks));
    
    // Live Tool Interleaving
    sse.addEventListener('tool_use', (e) => {
      const { tool } = JSON.parse(e.data);
      setLogs(prev => [...prev, { type: 'tool', text: `🔧 ${tool}` }]);
    });

    return () => sse.close();
  }, [sessionId]);

  return { tasks, logs };
};
```

---

## 2. The Swarm Task List UI

During a `POST /api/v1/chat` request (which can take 5-30s), the `task_list` event provides a real-time Kanban-style state.

### Task Object Schema
```json
{
  "tasks": [
    { "id": "task_grounding", "task": "Synthesizing grounding context", "status": "completed" },
    { "id": "task_intent", "task": "Analyzing query complexity", "status": "in_progress" },
    { "id": "task_execution", "task": "Executing Swarm Resolution", "status": "pending" },
    { "id": "task_validation", "task": "Validating safety constraints", "status": "pending" }
  ]
}
```

### UI Presentation Rule
Render this as a vertical checklist.
- **`completed`**: Green checkmark + text strike-through or dimmed.
- **`in_progress`**: Spinning loader or pulsing icon.
- **[pending](file:///e:/Automation/agent_commercial/api/routes_omega.py#475-482)**: Greyed out text.

---

## 3. Response Parsing: `<thinking>` and `<answer>`

The backend provides a "Chain of Thought" response. For the best UX, hide the internal reasoning behind an expander.

### Payload Structure
```text
<thinking>
I've checked the AHU-02 telemetry. Efficiency is low due to a stuck damper.
</thinking>
<answer>
The AHU-02 has a potential fault. I recommend a physical inspection...
</answer>
```

### Parsing & Timer Pattern
1.  **Start a Timer** immediately upon calling `POST /api/v1/chat`.
2.  **Display "⚡ Thinking..."** while the request is pending.
3.  **On Response Arrival**:
    - Stop the timer (e.g., "Thought for 12.4s").
    - Use Regex to extract `<thinking>` content and place it in a collapsible [details](file:///e:/Automation/agent_commercial/api/routes_omega.py#497-521) component.
    - Extract `<answer>` content and render it as the main Markdown message bubble.

```javascript
const parseArvisResponse = (raw) => {
  const thinking = raw.match(/<thinking>([\s\S]*?)<\/thinking>/i)?.[1] || "";
  const answer = raw.match(/<answer>([\s\S]*?)<\/answer>/i)?.[1] || raw.replace(/<thinking>[\s\S]*?<\/thinking>/gi, "");
  return { thinking: thinking.trim(), answer: answer.trim() };
};
```

---

## 4. UI Text Aliases
The backend already translates raw technical IDs and Agent names into "Friendly Aliases" (e.g., `Energy_Agent` → `Energy Optimizer`). Render the strings exactly as provided in the SSE data.

### Example Mapping (for reference)
- `predictive_engine` → `Predictive Maintenance Advisor`
- `fetch_live_telemetry` → `Checking live equipment telemetry...`

---

## 5. Session Persistence
Always pass `session_id` in `POST /api/v1/chat` if it's a follow-up question. If it's a new chat, leave `session_id` null, and the backend will return a new ID in the response for you to persist.
