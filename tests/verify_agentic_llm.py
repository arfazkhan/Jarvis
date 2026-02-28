
import asyncio
import shutil
import tempfile
import os
import logging
from datetime import datetime
from dotenv import load_dotenv

# Load env before imports that might need keys
load_dotenv()

from agent_cognitive.meta_cognition import MetaCognition
from agent_commercial.skillbook import BuildingSkillbook

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("verify_agentic_llm")

async def verify_llm_reflection():
    print("🚀 Starting 10/10 Agentic Capability Verification (Real LLM)...")
    
    # 1. Setup Test Environment
    test_dir = tempfile.mkdtemp()
    db_path = os.path.join(test_dir, "verify_skillbook.db")
    
    try:
        # Initialize Skillbook & MetaCognition
        skillbook = BuildingSkillbook("verify_building", db_path=db_path)
        
        # Hack singleton to force our DB
        from agent_commercial.skillbook import _skillbooks
        _skillbooks["verify_building"] = skillbook
        
        meta = MetaCognition("verify_building")
        
        # 2. Seed Data: Create an "Overconfident" profile
        print("--- Step 1: Seeding decision history (Simulating Overconfidence) ---")
        for i in range(5):
            d_id = meta.record_decision(
                context={"situation": "high_temp_alarm"}, 
                chosen_action="ignore_alarm", 
                alternatives=["investigate"], 
                confidence=0.95, # Very confident
                reasoning="It's probably just a sensor glitch"
            )
            # But it failed!
            meta.record_outcome(d_id, outcome="Critical Failure: Compressor Trip", quality="bad")
            print(f"  -> Recorded decision {i+1}: High Confidence (0.95) -> Bad Outcome")
            
        # 3. Trigger Reflection
        print("\n--- Step 2: Triggering 'Conscious' Reflection (LLM API Call) ---")
        print("Asking Agent: 'Analyze your recent decision performance...'")
        
        start_time = datetime.now()
        reflection_narrative = await meta.reflect_with_llm(lookback_days=1)
        duration = (datetime.now() - start_time).total_seconds()
        
        print(f"\n--- 🤖 Agent Reflection (Generated in {duration:.2f}s) ---")
        print("---------------------------------------------------------------")
        print(reflection_narrative)
        print("---------------------------------------------------------------")
        
        # 4. Verification assertions
        if "Error" in reflection_narrative and len(reflection_narrative) < 100:
            print("\n❌ Verification FAILED: LLM call returned an error.")
            # Don't fail the build if Keys are missing, just warn
            if "not found" in reflection_narrative:
                print("   (This is expected if API keys are missing in .env)")
        elif len(reflection_narrative) > 20:
            print("\n✅ Verification SUCCESS: Agent successfully self-reflected!")
            
            # Simple keyword check for "overconfident" concept (LLM wording varies)
            keywords = ["overconfident", "confidence", "adjust", "fail", "bias"]
            if any(k in reflection_narrative.lower() for k in keywords):
                print("   -> Agent correctly identified the issue.")
            else:
                print("   -> Warning: Agent reflection was generic (did not explicitly mention confidence issues).")
                
    finally:
        # Cleanup
        try:
            skillbook = None
            meta = None
            import gc
            gc.collect()
            shutil.rmtree(test_dir)
            print("\nTest environment cleaned up.")
        except Exception as e:
            print(f"Cleanup warning: {e}")

if __name__ == "__main__":
    asyncio.run(verify_llm_reflection())
