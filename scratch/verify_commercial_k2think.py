"""Verify commercial UnifiedLLM runs on K2Think with native tool-calling
when ARVIS_LLM_BACKEND=k2think (overriding Bedrock)."""
import asyncio
import os
from pathlib import Path

ROOT = Path(__file__).parent.parent
try:
    import dotenv
    dotenv.load_dotenv(str(ROOT / ".env"))
except Exception:
    pass

# Force the K2Think backend even though BEDROCK_API_KEY is in .env.
os.environ["ARVIS_LLM_BACKEND"] = "k2think"
os.environ["LLM_PROVIDER"] = "k2think"
os.environ["TOOL_PROVIDER"] = "k2think"

import sys
sys.path.insert(0, str(ROOT))
from agent_unified.llm import UnifiedLLM, _bedrock_enabled, _REASONING_AGENT  # noqa


async def main():
    print("bedrock_enabled (should be False):", _bedrock_enabled())
    llm = UnifiedLLM()
    import agent_unified.llm as m
    print("reasoning agent client:", type(getattr(m._REASONING_AGENT, "client", None)).__name__)
    print("tool agent client:", type(getattr(m._TOOL_AGENT, "client", None)).__name__)

    # 1) ask_json (reasoning channel)
    resp = await llm.ask_json(
        messages=[{"role": "user", "content": "Asset GEN-01 fuel at 8%. Reply JSON."}],
        system_msgs=[{"content": 'Output JSON: {"risk": str, "severity": str}'}],
        channel="reasoning")
    print("ask_json ->", resp if isinstance(resp, dict) else type(resp))

    # 2) native ask_tool
    tools = [{
        "type": "function",
        "function": {"name": "get_asset_state",
                     "description": "Get live state for an asset",
                     "parameters": {"type": "object",
                                    "properties": {"asset_id": {"type": "string"}},
                                    "required": ["asset_id"]}}}]
    msg = await llm.ask_tool(
        messages=[{"role": "user", "content": "Check the state of asset GEN-01."}],
        system_msgs=[{"content": "Use tools to gather data."}],
        tools=tools, tool_choice="auto", channel="tool")
    tcs = getattr(msg, "tool_calls", None) or []
    print(f"ask_tool -> {len(tcs)} tool_call(s)")
    for tc in tcs:
        print("   ", tc.function.name, "args=", tc.function.arguments)

    ok = isinstance(resp, dict) and resp and len(tcs) >= 1
    print("\nRESULT:", "PASS — commercial on K2Think with native tool-calling" if ok else "PARTIAL/FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
