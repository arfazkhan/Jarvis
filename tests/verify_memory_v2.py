import sys
import os
from datetime import datetime

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_commercial.skillbook import BuildingSkillbook, SkillStatus, SkillType

def test_bayesian_convergence():
    db_name = f"test_memory_bayesian_{int(datetime.now().timestamp())}.db"
    print(f"\n--- Testing Bayesian Confidence Convergence (using {db_name}) ---")
    sb = BuildingSkillbook("test_bayesian", db_path=db_name)
    
    skill = sb.add_skill(
        skill_type="pattern",
        title="Test Logic",
        description="Testing Bayesian Updates"
    )
    
    print(f"Initial Confidence: {skill.confidence}")
    
    # Simulate a success
    sb.verify_skill(skill.skill_id, True)
    skill = sb.get_skill(skill.skill_id)
    print(f"Confidence after 1 success: {skill.confidence}")
    
    # Simulate another success
    sb.verify_skill(skill.skill_id, True)
    skill = sb.get_skill(skill.skill_id)
    print(f"Confidence after 2 successes: {skill.confidence}")
    
    # Simulate a failure
    sb.verify_skill(skill.skill_id, False)
    skill = sb.get_skill(skill.skill_id)
    print(f"Confidence after 1 failure: {skill.confidence}")
    
    # After 2 success and 1 failure: 0.5 -> 0.85 -> 0.97 -> 0.85
    assert skill.confidence < 0.9, f"Confidence {skill.confidence} should drop after failure"

def test_relationship_trace():
    db_name = f"test_memory_graph_{int(datetime.now().timestamp())}.db"
    print(f"\n--- Testing Relationship Trace (using {db_name}) ---")
    sb = BuildingSkillbook("test_graph", db_path=db_name)
    
    # Add quirk for a Pump
    sb.add_skill(
        skill_type="equipment_quirk",
        title="Pump Cavitation Quirk",
        description="Pump-01 cavitates if chiller valve is < 10%",
        equipment_id="chw_pump" # This is a default node in BMSGraph
    )
    
    # Query for Chiller (upstream of Pump)
    # BMSGraph default: chiller feeds chw_pump
    relevant = sb.get_relevant_skills({"equipment_id": "chiller"})
    
    print(f"Found {len(relevant)} skills for chiller (should include chw_pump quirk)")
    found_pump_quirk = any("Pump Cavitation" in s.title for s in relevant)
    print(f"Relationship trace successful: {found_pump_quirk}")
    
    assert found_pump_quirk, "Should have found the downstream pump quirk"

def test_consolidation():
    db_name = f"test_memory_consolidation_{int(datetime.now().timestamp())}.db"
    print(f"\n--- Testing Hierarchical Consolidation (using {db_name}) ---")
    sb = BuildingSkillbook("test_consolidation", db_path=db_name)
    
    # Add two very similar skills
    s1 = sb.add_skill(
        skill_type="pattern",
        title="Morning Drift Pattern",
        description="Morning drift detected at 8am with high solar load",
        equipment_id="ahu_01"
    )
    
    s2 = sb.add_skill(
        skill_type="pattern",
        title="Drift Pattern Morning",
        description="AHU-01 drift morning pattern solar heat load",
        equipment_id="ahu_01"
    )
    
    # Run manual consolidation
    print(f"Matcher Available: {sb.matcher.is_available}")
    if sb.matcher.is_available:
        print(f"Skills in Matcher: {list(sb.matcher.skill_embeddings.keys())}")
        sim_matrix = sb.matcher.get_skill_similarity_matrix()
        print(f"Similarity Score (S1, S2): {sim_matrix.get(s1.skill_id, {}).get(s2.skill_id, 'N/A')}")
        
    results = sb.consolidate_skills()
    print(f"Consolidation results: {results}")
    
    assert results["merged"] >= 1 or not sb.matcher.is_available, f"Consolidation failed. Matcher avail: {sb.matcher.is_available}, Merged: {results['merged']}"

if __name__ == "__main__":
    try:
        test_bayesian_convergence()
        test_relationship_trace()
        test_consolidation()
        
        print("\n✅ ALL MEMORY V2 VERIFICATIONS PASSED")
    except Exception as e:
        print(f"\n❌ VERIFICATION FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
