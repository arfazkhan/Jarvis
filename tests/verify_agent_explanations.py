
import asyncio
import logging
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

from agent_bms.bms_llm_agent import BMSLLMAgent
from agent_bms.database import get_database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("verify_agent_explainer")

async def verify_agent_explanations():
    print("🚀 Starting Agent-Level Explanation Verification...")
    
    # 1. Initialize Agent with a mock AlarmEngine
    from unittest.mock import MagicMock
    mock_alarm_engine = MagicMock()
    # Ensure it returns a report with a recommendation
    mock_report = MagicMock()
    mock_report.to_dict.return_value = {
        "alarm_id": "ALM-HIGH-TEMP-01",
        "root_cause_id": "CH-01",
        "recommendation": "Inspect Chiller-01 condenser pumps and clear debris."
    }
    mock_alarm_engine.get_root_cause_analysis.return_value = mock_report
    
    agent = BMSLLMAgent(alarm_engine=mock_alarm_engine)
    
    # 2. Mock an alarm in the engine
    alarm_id = "ALM-HIGH-TEMP-01"
    # Note: AlarmEngine handles RCAs internally. 
    # For this test, we assume the alarm_engine has data for this ID.
    
    # 3. Call explain_alarm tool
    print("\n--- Executing 'explain_alarm' tool ---")
    args = {"alarm_id": alarm_id}
    
    try:
        result = await agent.tool_handler.execute("explain_alarm", args)
        
        print(f"Tool Result Title: {result.get('recommendation', 'N/A')}")
        
        if "high_fidelity_explanation" in result:
            print("\n✅ High-Fidelity Explanation Found:")
            print(f"Explanation: {result['high_fidelity_explanation']}")
            print(f"Causal Chain: {' -> '.join(result.get('causal_chain', []))}")
        else:
            print("\n❌ High-Fidelity Explanation MISSING in result.")
            print(f"Keys present: {list(result.keys())}")
            
    except Exception as e:
        print(f"❌ Tool execution failed: {e}")
        import traceback
        traceback.print_exc()

    print("\n✅ Verification COMPLETE.")

if __name__ == "__main__":
    asyncio.run(verify_agent_explanations())
