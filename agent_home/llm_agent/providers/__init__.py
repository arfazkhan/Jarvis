"""
LLM Providers Module
====================

Modular provider implementations for the LLM Agent.
Supports multiple LLM backends with a unified interface.

Providers:
- gemini: Google Gemini 2.0 Flash
- groq: Groq Llama models
- openai: OpenAI GPT models
- k2think: K2 Think reasoning model
- lmstudio: Local LM Studio
- openrouter: OpenRouter multi-model gateway
- synthetic: Synthetic API
- colab: Custom Colab/ngrok endpoint
"""

from agent_home.llm_agent.providers.base import BaseProvider
from agent_home.llm_agent.providers.gemini import GeminiProvider
from agent_home.llm_agent.providers.groq import GroqProvider
from agent_home.llm_agent.providers.openai import OpenAIProvider
from agent_home.llm_agent.providers.k2think import K2ThinkProvider
from agent_home.llm_agent.providers.lmstudio import LMStudioProvider
from agent_home.llm_agent.providers.openrouter import OpenRouterProvider

__all__ = [
    "BaseProvider",
    "GeminiProvider",
    "GroqProvider",
    "OpenAIProvider",
    "K2ThinkProvider",
    "LMStudioProvider",
    "OpenRouterProvider",
]