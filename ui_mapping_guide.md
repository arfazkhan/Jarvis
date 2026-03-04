# UI Mapping Guide: Omega Infinity Artifacts

This guide explains how to map the internal simulation events and logs to specific UI components such as "Thinking", "Tool Calls", and "Plans".

## 1. Thinking (Internal Monologue)
Shows the agent's internal reasoning process before or during actions.

- **Event Type**: `think` (via Tool Use) or `progress` (via Turn Summary).
- **Log Pattern**: `UI_LOG: Morning briefing...` or lines ending in `-> INVESTIGATED`.
- **SSE Payload**:
  ```json
  {
    "event": "tool_use",
    "data": {
      "tool": "think",
      "args": { "reasoning": "[PLAN] Analyzing vibration drift on CH-01..." },
      "step": 1
    }
  }
  ```
- **UI Implementation**: Display the `reasoning` string in a "Thought Process" or "Mental Model" accordion.

## 2. Plans (Strategy)
Shows the sequence of tools the agent intends to call for the current objective.

- **Event Type**: `plan`
- **Source**: Emitted at the start of each ReAct turn in [bms_llm_agent.py](file:///e:/Automation/agent_commercial/bms_llm_agent.py).
- **SSE Payload**:
  ```json
  {
    "event": "plan",
    "data": {
      "step": 1,
      "planned_tools": ["get_equipment_status", "analyze_energy", "think"],
      "reasoning": "Verify chiller health before checking energy correlations."
    }
  }
  ```
- **UI Implementation**: Use a horizontal step-indicator or a "Next Actions" list using the `planned_tools` array.

## 3. Tool Calls (Execution)
Shows the specific functions being executed and their arguments.

- **Event Type**: `tool_use` (Input) and [tool_result](file:///e:/Automation/agent_commercial/bms_llm_agent.py#1184-1208) (Output).
- **Log Pattern**: Traceable via `agent_commercial/tools/` execution logs.
- **SSE Payload (Input)**:
  ```json
  {
    "event": "tool_use",
    "data": {
      "tool": "get_equipment_status",
      "args": { "equipment_id": "CHILLER-01" },
      "status": "running"
    }
  }
  ```
- **SSE Payload (Output)**:
  ```json
  {
    "event": "tool_result",
    "data": {
      "tool": "get_equipment_status",
      "result": "Status: RUNNING, Vibration: 3.2mm/s, Temp: 7.2C"
    }
  }
  ```
- **UI Implementation**: A "Console" or "Activity Log" component showing function names and their corresponding JSON results.

## 4. Task List (Objectives)
The high-level "To-Do" list derived dynamically from the user's query.

- **Event Type**: `task_list`
- **SSE Payload**:
  ```json
  {
    "event": "task_list",
    "data": {
      "tasks": [
        { "id": "data_fault", "task": "Investigate equipment telemetry", "status": "completed" },
        { "id": "reason", "task": "Synthesize findings", "status": "in-progress" }
      ]
    }
  }
  ```
- **UI Implementation**: A sidebar checklist that updates its `status` (todo, in-progress, completed) in real-time.

## Summary Table

| UI Requirement | Event Key | Key Field | Source Component |
| :--- | :--- | :--- | :--- |
| **Thinking** | `think` / `progress` | `reasoning` / `content` | `BMSLLMAgent` + `Sovereign Tool` |
| **Plans** | `plan` | `planned_tools` | `BMSLLMAgent._generate_tool_calls` |
| **Tool Calls** | `tool_use` | `tool`, `args` | `ToolHandler` |
| **Final Summary** | `summary` | `content` | `BMSLLMAgent._generate_final_summary` |
