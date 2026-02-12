import asyncio
import logging
from agent_bms.bms_llm_agent import BMSLLMAgent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("arvis.test.graph_rag")

async def verify_graph_rag():
    print("\n" + "="*80)
    print("🚀 STARTING PHASE 8: GRAPH-RAG VERIFICATION")
    print("="*80)
    
    agent = BMSLLMAgent()
    
    # 1. SETUP THE GRAPH (Topology)
    # Chiller -> AHU-01 -> VAV-01
    print("\n[GRAPH] Building building topology...")
    agent.context_graph.add_node("CH-01", "chiller", {"model": "Carrier 19XR"})
    agent.context_graph.add_node("AHU-01", "ahu", {"parent": "CH-01"})
    agent.context_graph.add_node("VAV-01", "vav", {"parent": "AHU-01"})
    
    agent.context_graph.add_edge("CH-01", "AHU-01", "feeds_water")
    agent.context_graph.add_edge("AHU-01", "VAV-01", "feeds_air")

    # 2. SEED KNOWLEDGE BASE (Manuals)
    print("\n[KB] Indexing separate manuals for different equipment...")
    
    # Chiller Manual (High-level system safety)
    agent.knowledge_base.index_technical_snippet(
        content="CH-01 SYSTEM SAFETY: Maximum condensation pressure 250 psi.",
        source="Chiller_Main_Manual.pdf",
        equipment_id="CH-01"
    )
    
    # VAV Manual (Component specific)
    agent.knowledge_base.index_technical_snippet(
        content="VAV-01 OPERATION: Maximum damper position 95%.",
        source="VAV_Operation_Guide.pdf",
        equipment_id="VAV-01"
    )

    # 3. TEST GRAPH-RAG (Deep Search)
    print("\n[TEST] Querying VAV-01 with system_depth=2 (Should find Chiller info)...")
    result = await agent.tool_handler.execute("get_equipment_specs", {
        "query": "safety limits and pressure",
        "equipment_id": "VAV-01",
        "system_depth": 2
    })
    
    findings = result.get("findings", [])
    print(f"Graph-RAG Findings: {findings}")
    
    # Check if we found info from BOTH the VAV and the Chiller
    has_vav_info = any("95%" in f for f in findings)
    has_chiller_info = any("250 psi" in f for f in findings)
    
    if has_vav_info and has_chiller_info:
        print("\n✅ GRAPH-RAG SUCCESS: Retrieval correctly traversed the graph from local component to central plant!")
    else:
        if not has_vav_info: print("❌ Missing VAV info.")
        if not has_chiller_info: print("❌ Missing Chiller info (Graph traversal failed).")

    print("\n" + "="*80)
    print("✅ PHASE 8 VERIFICATION COMPLETE")
    print("="*80)

if __name__ == "__main__":
    asyncio.run(verify_graph_rag())
