# Custom Chat Interface Frontend Implementation Guide

This guide covers how to wire up the React components for the interactive "Ask ARVIS" chat using the stateful conversation sessions and the new user-friendly SSE streams we implemented on the backend.

---

## 1. Chat History / Session Management

The chat API `POST /api/v1/chat` is no longer a stateless transaction. It now requires an ongoing `session_id` to remember context.

### Fetching Previous Sessions
When the user opens the chat slider, you should fetch their recent sessions to populate the historical sidebar.

```javascript
// Fetch all sessions
const fetchSessions = async () => {
    const response = await fetch('/api/v1/chat/sessions', {
        headers: { 'Authorization': `Bearer ${userToken}` }
    });
    const data = await response.json();
    setSessions(data.sessions); // Array of { session_id, title, updated_at }
};

// Fetch a specific session's message history when clicked
const loadSessionHistory = async (sessionId) => {
    const response = await fetch(`/api/v1/chat/sessions/${sessionId}/history`, {
        headers: { 'Authorization': `Bearer ${userToken}` }
    });
    const data = await response.json();
    setMessages(data.history); // Array of { role: "user" | "assistant", content }
    setActiveSessionId(sessionId);
};
```

### Sending Messages
When the user types a new message, pass the `activeSessionId` if one exists. If it is null, the backend will generate a new session and hand you the ID.

```javascript
const sendMessage = async (query) => {
    const payload = { query };
    if (activeSessionId) {
        payload.session_id = activeSessionId;
    }

    const response = await fetch('/api/v1/chat', {
        method: 'POST',
        headers: {
            'Authorization': `Bearer ${userToken}`,
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
    });

    const data = await response.json();
    
    // Crucial: Update active session id so subsequent messages thread correctly
    if (!activeSessionId && data.session_id) {
        setActiveSessionId(data.session_id);
    }
    
    // Add the final response to chat UI
    setMessages(prev => [...prev, { role: "assistant", content: data.response }]);
};
```

---

## 2. Server-Sent Events (SSE) Stream

While the `POST /chat` call is blocking (waiting ~5 to ~30 seconds), you should be listening to the SSE Stream `GET /api/v1/stream/thoughts` to show the user exactly what the AI is doing.

Because we added backend [formatters.py](file:///e:/Automation/agent_commercial/api/formatters.py), you **do not** need to parse variables anymore. The server hands you beautifully formatted strings ready for UI injection.

### SSE Stream Connection Hook
```javascript
import { useEffect, useState } from 'react';

const useArvisStream = () => {
  const [streamEvents, setStreamEvents] = useState([]);
  const [taskState, setTaskState] = useState([]);

  useEffect(() => {
    const eventSource = new EventSource('http://127.0.0.1:8000/api/v1/stream/thoughts');

    // 1. Tool Execution Events
    // Example: { "tool": "Checking live equipment telemetry...", "success": true, "duration_ms": 14.2 }
    eventSource.addEventListener('tool_use', (event) => {
      const data = JSON.parse(event.data);
      setStreamEvents(prev => [...prev, { type: 'tool', text: `🔧 ${data.tool}` }]);
    });

    // 2. Agent Thought Events
    // Example: { "node": "Energy Optimizer", "content": "The user is asking about..." }
    eventSource.addEventListener('thought', (event) => {
      const data = JSON.parse(event.data);
      setStreamEvents(prev => [...prev, { type: 'thought', text: `🧠 ${data.node} is thinking...` }]);
    });

    // 3. Task List Updates (Consensus progress)
    // The backend sends a complete array of tasks with 'pending', 'in_progress', or 'completed' status.
    eventSource.addEventListener('task_list', (event) => {
      const data = JSON.parse(event.data);
      if (data && data.tasks) {
         setTaskState(data.tasks); 
      }
    });

    return () => {
      eventSource.close();
    };
  }, []);

  return { streamEvents, taskState };
};
```

### Example Payload Progression
This is exactly what the SSE payload pushing to your React component looks like in real time during a complex query:

**Event 1:** [thought](file:///e:/Automation/agent_commercial/api/routes_omega.py#56-87)
```json
{
  "node": "Strategic AI",
  "content": "The user wants to simulate changing the AHU-01 cooling setpoint..."
}
// Renders as: 🧠 Strategic AI is thinking...
```

**Event 2:** `tool_use`
```json
{
  "tool": "Simulating environmental impact of proposed changes...",
  "args": {
    "equipment_id": "AHU-01"
  },
  "success": true,
  "duration_ms": 32.54
}
// Renders as: 🔧 Simulating environmental impact of proposed changes...
```

**Event 3:** `task_list`
```json
{
  "tasks": [
    {
      "id": "task_grounding",
      "task": "Synthesizing real-time grounding context",
      "status": "completed"
    },
    {
      "id": "task_intent",
      "task": "Analyzing query intent and complexity",
      "status": "in_progress"
    },
    {
      "id": "task_execution",
      "task": "Executing Swarm Resolution (BFT / Fast-Path)",
      "status": "pending"
    },
    {
      "id": "task_validation",
      "task": "Validating output against safety constraints",
      "status": "pending"
    }
  ]
}
```
*Renders as a To-Do list where "Synthesizing" has a green checkmark, "Analyzing" has a spinning loader, and the rest are greyed out.*

By rendering these tasks as a visual checklist alongside the interleaved Agent thoughts and Tool usages, you create a beautiful "Glass Box" effect where the user can watch the AI orchestrating building optimizations live without overwhelming them with raw JSON function calls.
