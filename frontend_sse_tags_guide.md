# Frontend Guide: SSE Streams, Aliases, & Global Progress UI

This document explains how to consume the ARVIS Server-Sent Events (SSE) stream to build a "Glass Box" UI. 

Because ARVIS runs constant background cognitive loops (learning, simulating, checking alarms) even when the user *isn't* chatting, this SSE stream should be hooked up **globally** to your React app (e.g., in a top navigation bar, timeline, or floating action button) to show overarching building intelligence activity.

---

## 1. Global SSE Stream Connection
The `GET /api/v1/stream/thoughts` endpoint broadcasts all active Swarm tasks.

**Implementation Strategy:**
Mount the SSE listener at the *root* of your React app (e.g., in `App.jsx` or a global Context Provider). This allows you to render a small "ARVIS Status" widget in the header that pulses or shows background tasks independently of the Chat sidebar.

```javascript
// Global Context Example (Simplified)
import { useEffect, useState } from 'react';

export const useGlobalArvisStream = () => {
  const [activeBackgroundRoutine, setActiveBackgroundRoutine] = useState(null);
  const [taskState, setTaskState] = useState([]); // The To-Do Checklist

  useEffect(() => {
    const eventSource = new EventSource('http://127.0.0.1:8000/api/v1/stream/thoughts');

    // Catches tool_use, thought, and task_list events
    eventSource.addEventListener('tool_use', (e) => {
        setActiveBackgroundRoutine(`🔧 ${JSON.parse(e.data).tool}`);
    });
    
    eventSource.addEventListener('task_list', (e) => {
        setTaskState(JSON.parse(e.data).tasks);
    });

    return () => eventSource.close();
  }, []);

  return { activeBackgroundRoutine, taskState };
};
```

---

## 2. Global Background Monitoring vs. Active Chat

Here is how the UI should react in the two distinct interaction states:

### State A: Passive Background Monitoring (User is NOT chatting)
While the user browses the Overview or Timeline dashboard, ARVIS might suddenly run a background cron job (e.g., the Maintenance Agent running a predictive analysis).

1. Global Stream picks up [thought](file:///e:/Automation/agent_commercial/api/routes_omega.py#56-87): "🧠 Predictive Maintenance Advisor is thinking..."
2. Your Global Header Widget gently pulses or shows a subtle toast notification.
3. Global Stream picks up `tool_use`: "🔧 Scanning equipment for hidden faults..."
4. User knows the AI is watching the building without needing to ask.

### State B: Active Chat (User hits "Send")
1. The user opens the Chat sidebar and asks: "Simulate an AHU temperature change."
2. The user's query triggers a blocking `POST /api/v1/chat`.
3. The SSE stream immediately lights up with a specific `task_list` array.
4. The Chat Sidebar UI dynamically renders this array as a Kanban-style To-Do list (Pending -> In Progress -> Completed).
5. When `POST` returns 200 OK, the UI collapses the To-Do list, strips the `<thinking>` tags (see section 4), and shows the final Markdown response.

---

## 3. The ARVIS UI Aliases Dictionary
The backend automatically formats raw API endpoints and Agent internal names into these user-friendly strings before sending them down the SSE stream. Your React code **does not** need to do this translation; just render what arrives on the stream!

### Friendly Agents
* `Energy Optimizer` (Energy_Agent)
* `Thermal Comfort Specialist` (Comfort_Agent)
* `Strategic AI` (Strategic_Agent)
* `Anomaly Detector` (Alarm_Agent)
* `Predictive Maintenance Advisor` (Maintenance_Agent)
* `Knowledge Graph` (Memory_Agent)
* `Chief Building AI` (Sovereign_Agent)
* `Quick Inquiry Router` (Fast_Router)

### Friendly Tools (BMS Operations)
* `Consulting historical building skillbook...`
* `Recording new knowledge to skillbook...`
* `Comparing baseline with equivalent buildings...`
* `Simulating environmental impact of proposed changes...`
* `Correlating system events and logs...`
* `Running AI energy forecast...`
* `Scanning equipment for hidden faults...`
* `Performing ML root cause analysis...`
* `Running Monte Carlo impact simulations...`
* `Cross-referencing historical problem solutions...`
* `Benchmarking ML efficiency models...`
* `Running predictive maintenance algorithms...`
* `Estimating remaining useful life for equipment...`
* `Cross-checking recent maintenance logs...`
* `Checking GSAS sustainability compliance...`
* `Calculating GSAS score improvement priorities...`
* `Formatting data for GORD reporting...`
* `Checking live equipment telemetry...`
* `Syncing equipment inventory...`
* `Evaluating equipment health metrics...`
* `Retrieving historical sensor telemetry...`
* `Looking up engineering specifications...`
* `Refreshing dashboard overview metrics...`
* `Analyzing real-time energy consumption patterns...`
* `Searching for localized energy anomalies...`
* `Calculating financial cost impact of operations...`
* `Calculating current utility burn rates...`
* `Scanning for empty spaces consuming power...`
* `Estimating human occupancy density by zone...`
* `Scanning active alarm registers...`
* `Analyzing alarm diagnostic context...`
* `Attempting to acknowledge system alarm...`
* `Tracing alarm cascade root-cause...`
* `Fetching highest confidence strategic recommendations...`
* `Evaluating alignment with building KPI goals...`
* `Compiling executive operations briefing...`
* `Executing interactive briefing session...`
* `Logging operator feedback to neural core...`
* `Retrieving Swarm truth and confidence metrics...`

---

## 4. Final Response Parsing: `<answer>` and `<thinking>` Tags

The final Markdown string from `POST /api/v1/chat` has a well-defined structure. It **always** wraps the user-facing content in `<answer>` tags and may optionally include internal reasoning in `<thinking>` tags that must be hidden.

### Expected Payload Structure
```text
<thinking>
I have reviewed the tool results and confirmed the data is grounded.
Now formatting the response for the user.
</thinking>
<answer>
The AHU-01 is currently operating at nominal parameters.
Supply Air Temperature: 22.4°C ✅
Active Alarms: None
</answer>
```

### Implementation Rule
1. **Extract `<answer>`**: The text you display in the chat bubble should be **only** the content between `<answer>` and `</answer>`.
2. **Show `<thinking>` as a timed collapsible toggle**: While the AI is running (blocking `POST`), display a pulsing **"⚡ Thinking..."** label above the response area. Once the answer arrives, freeze the elapsed time and change the label to **"Thought for X seconds"** (collapsed by default). The user can click to expand and read the raw reasoning.

### Thinking → Thought Timer Pattern
```javascript
// Track when the POST was sent
const [thinkingStartTime, setThinkingStartTime] = useState(null);
const [thinkingDuration, setThinkingDuration] = useState(null);
const [thinkingContent, setThinkingContent] = useState('');

const sendMessage = async (query) => {
    const startTime = Date.now();
    setThinkingStartTime(startTime);
    setThinkingDuration(null); // Show "Thinking..." while pending
    
    const data = await postToChat(query);
    
    // Freeze the timer once the answer arrives
    const elapsedSeconds = ((Date.now() - startTime) / 1000).toFixed(1);
    setThinkingDuration(elapsedSeconds);
    
    // Extract the <thinking> block to show in the collapsed expander
    const thinkingMatch = data.response.match(/<thinking>([\s\S]*?)<\/thinking>/i);
    if (thinkingMatch) setThinkingContent(thinkingMatch[1].trim());
    
    // Extract the clean <answer> for the main bubble
    setMessages(prev => [...prev, { role: "assistant", content: parseArvisResponse(data.response) }]);
};

// In your JSX:
// {thinkingDuration == null 
//   ? <span className="pulse">⚡ Thinking...</span> 
//   : <details><summary>🧠 Thought for {thinkingDuration}s</summary><p>{thinkingContent}</p></details>
// }
```

### JavaScript Parser Helper
```javascript
// Strips thinking tags and extracts the answer
const parseArvisResponse = (rawText) => {
    // Remove all <thinking>...</thinking> blocks
    const noThinking = rawText.replace(/<thinking>[\s\S]*?<\/thinking>/gi, '').trim();
    
    // Extract the <answer> block if present
    const answerMatch = noThinking.match(/<answer>([\s\S]*?)<\/answer>/i);
    if (answerMatch) {
        return answerMatch[1].trim(); // Return just the inner content
    }
    
    // Fallback: if no <answer> tag, return the cleaned text as-is
    return noThinking;
};

// Usage after POST /api/v1/chat returns:
const cleanedResponse = parseArvisResponse(data.response);
setMessages(prev => [...prev, { role: "assistant", content: cleanedResponse }]);
```
