# System Architecture

## Overview
The Home Agent is a modular, event-driven system designed for autonomous home automation. It leverages a local LLM for reasoning and natural language understanding, combined with deterministic rule engines for safety and reliability.

## Core Components

### 1. Event Bus (`agent/event_bus`)
The central nervous system. All components communicate via the `EventBus` using a publish-subscribe model. This ensures loose coupling and easy extensibility.

### 2. State Engine (`agent/state_engine`)
Maintains the "Source of Truth" for the home environment. It tracks:
- **Entities**: Devices (lights, locks, sensors).
- **Context**: User presence, time of day, active modes.
- **History**: Short-term history of state changes.

### 3. Dialogue Manager (`agent_conversation`)
Handles all user interaction.
- **Input**: Voice (transcribed) or Text.
- **NLU**: Intent classification (Regex/Keyword + LLM fallback).
- **Output**: Natural language responses (TTS-ready).
- **Interaction Loop**: Manages the flow between input, processing, and response.

### 4. Mission Execution Layer (`agent_mission`)
Responsible for long-running, multi-step tasks.
- **Mission**: A high-level goal (e.g., "Clean the house").
- **MissionPlanner**: Breaks down missions into a `PlanGraph`.
- **MissionExecutor**: Executes the plan, handling retries, pauses, and recovery.
- **ActionRouter**: Dispatches steps to specific executors (`DeviceExecutor`, `SceneExecutor`, etc.).

### 5. Personality Engine (`agent_personality`)
Injects "soul" into the agent.
- **Persona**: Defines the agent's character (e.g., "Jarvis", "Helpful Assistant").
- **EmotionEngine**: Tracks emotional state based on interactions and outcomes.
- **ToneAdapter**: Adjusts response style based on context and emotion.

### 6. Cognitive Layer (`agent_cognitive`)
Handles higher-level reasoning.
- **CognitiveLoop**: Background process for continuous analysis.
- **ContextGraph**: semantic relationships between entities.

### 7. Planning & Adaptation (`agent_plan`)
- **PlanGenerator**: Creates execution plans from intents.
- **AdaptivePlanEngine**: Modifies plans based on user preferences and feedback.
- **SafetyValidator**: Ensures plans are safe before execution.

## Data Flow
1. **User Input** -> `InteractionLoop` -> `DialogueManager`
2. **Intent** -> `MissionManager` (if complex) OR `PlanExecutor` (if simple)
3. **Execution** -> `ActionRouter` -> `DeviceExecutor` -> `MatterController` -> **Hardware**
4. **Feedback** -> `SensorIngestion` -> `StateEngine` -> `EventBus` -> `InteractionLoop` (Response)

## Technology Stack
- **Language**: Python 3.10+
- **LLM**: Local Llama-based model (via Groq or local inference).
- **Protocol**: Matter-over-Thread (simulated or real).
- **Storage**: SQLite (Preferences, Missions), In-Memory (State).
