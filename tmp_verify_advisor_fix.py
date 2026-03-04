import asyncio
import logging
import sys
import os

# Ensure project root is in path
sys.path.insert(0, os.getcwd())

from agent_advisory.multi_option_advisor import MultiOptionAdvisor

async def verify_advisor():
    logging.basicConfig(level=logging.INFO)
    print("Initializng MultiOptionAdvisor...")
    advisor = MultiOptionAdvisor()
    
    print("\nCalling get_recommendations (Tool Compatible Wrapper)...")
    try:
        # Simulate tool call
        result = await advisor.get_recommendations(
            context="High humidity in Server Room B",
            equipment_id="AHU-05",
            top_k=2
        )
        
        print("\nTool Response:")
        import json
        print(json.dumps(result, indent=2))
        
        if "recommendations" in result and len(result["recommendations"]) > 0:
            print("\nSUCCESS: get_recommendations returned recommendations!")
        else:
            print("\nFAILURE: get_recommendations returned no recommendations.")
            
    except AttributeError as e:
        print(f"\nFAILURE: AttributeError still present: {e}")
    except Exception as e:
        print(f"\nFAILURE: An unexpected error occurred: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(verify_advisor())
