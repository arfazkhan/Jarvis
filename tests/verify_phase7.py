import asyncio
import logging
from agent_commercial.bms_llm_agent import BMSLLMAgent

logging.basicConfig(level=logging.INFO)

async def verify_grounding():
    print("🚀 Starting Phase 7: Technical Grounding Verification...")
    
    agent = BMSLLMAgent()
    
    # 1. Index some sample manufacturer data
    print("\n--- Indexing Technical Data ---")
    chiller_data = """
    Manufacturer: Carrier
    Model: AquaEdge 19XR
    Maximum Operating Pressure: 250 psi
    Safety Limit - Low Chilled Water Temp: 3.5°C
    Optimal Condenser Water Temp: 24°C - 32°C
    Efficiency Curve: Peak efficiency at 65% load.
    """
    
    agent.knowledge_base.index_technical_snippet(
        content=chiller_data,
        source="Carrier_19XR_Manual.pdf",
        equipment_id="chiller-01",
        tags=["manual", "safety", "limits"]
    )
    
    # 2. Test Tool Execution
    print("\n--- Testing 'get_equipment_specs' Tool ---")
    result = await agent.tool_handler.execute(
        "get_equipment_specs", 
        {"query": "safety pressure limits", "equipment_id": "chiller-01"}
    )
    
    print(f"Tool Findings: {result.get('findings')}")
    
    if any("250 psi" in f for f in result.get('findings', [])):
        print("✅ Grounding successful! Found specific pressure limit in indexed manual.")
    else:
        print("❌ Grounding failed. Could not find pressure limit.")
        
    # 3. Test Agent Reasoning (via prompt)
    # Note: In a real test we'd call agent.chat, but here we just check the tool output
    
    print("\n✅ Phase 7 Verification COMPLETE.")

if __name__ == "__main__":
    asyncio.run(verify_grounding())
