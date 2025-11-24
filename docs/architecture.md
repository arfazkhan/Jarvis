# Home Agent Architecture

## 1. Overview
Home Agent is an AI-driven home automation system that combines:
- Matter-over-Thread hardware (ESP32-H2)
- A local Python intelligence agent
- A pub/sub event architecture
- LLM-based reasoning and planning
- Automations and learning modules

## 2. Core Components
1. **Event Bus**: Central pub/sub system (`agent.event_bus`).
2. **State Engine**: Tracks device state and history (`agent.state_engine`).
3. **LLM Agent**: Reasoner using Groq API (`agent.llm_agent`).
4. **Tool Executor**: Executes actions (`agent.tools`).
5. **Matter Controller**: Interface to hardware (`agent.controllers`).
6. **Automation Engine**: Manages routines (`agent.automations`).
7. **Learning Engine**: Periodic pattern analysis (`agent.learning`).

## 3. Data Flow
Event -> State Update -> LLM Reasoning -> Tool Calls -> Device Action -> New Event

## 4. Configuration
- Settings in `config/settings.py`
- Logging in `agent/utils/logging_config.py`
