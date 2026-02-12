"""
Verification script for Phase 2 Integration
=========================================

Verifies that:
1. BMSLLMAgent initializes with Phase 2 MultiOptionAdvisor
2. BMSToolHandler exposes the 'get_advisory_recommendations' tool
3. The tool returns properly structured advisory recommendations
4. The models are loaded and functioning (fallback or trained)
"""

import sys
import os
import asyncio
import logging
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agent_bms.bms_llm_agent import BMSLLMAgent

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("arvis.test")

async def verify_integration():
    logger.info("Initializing BMSLLMAgent...")
    
    # Initialize agent without full backend engines (mock mode)
    agent = BMSLLMAgent()
    
    # 1. Verify Advisor Initialization
    if hasattr(agent, "advisor") and agent.advisor is not None:
        logger.info("✅ BMSLLMAgent initialized with MultiOptionAdvisor")
        logger.info(f"   Advisor components: {agent.advisor.tracker}, {agent.advisor.preference_learner}")
    else:
        logger.error("❌ BMSLLMAgent failed to initialize MultiOptionAdvisor")
        return
    
    # 2. Verify Tool Registration
    tools = agent.tools
    advisory_tool = next((t for t in tools if t["name"] == "get_advisory_recommendations"), None)
    
    if advisory_tool:
        logger.info("✅ 'get_advisory_recommendations' tool registered in schema")
    else:
        logger.error("❌ 'get_advisory_recommendations' tool NOT found in schema")
        return

    # 3. Execution Verification
    logger.info("Testing tool execution...")
    
    mock_args = {
        "issue_type": "alarm",
        "context_description": "High pressure alarm on Chiller 1 (CH-01) in Zone A",
        "equipment_id": "CH-01"
    }
    
    try:
        result = await agent.tool_handler.execute("get_advisory_recommendations", mock_args)
        
        # Check structure
        if "prediction" in result and "options" in result:
            options = result["options"]
            logger.info(f"✅ Tool execution successful. Generated {len(options)} options.")
            
            # Print first option details
            if options:
                top_opt = options[0]
                logger.info(f"   Top recommended action: {top_opt.get('action_type')}")
                logger.info(f"   Ranking score: {top_opt.get('score')}")
                logger.info(f"   Explanation: {top_opt.get('explanation')}")
                
            # Verify outcome prediction
            # Verify outcome prediction
            outcome = result.get("prediction", {})
            logger.info(f"   Predicted Outcome: {outcome.get('predicted_quality')} (Utility: {outcome.get('predicted_utility')}, Confidence: {outcome.get('confidence')})")
            
        else:
            logger.error(f"❌ Unexpected result format: {list(result.keys())}")
            logger.error(f"   Result content: {result}")
            
    except Exception as e:
        logger.error(f"❌ Tool execution failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(verify_integration())
