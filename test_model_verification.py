import asyncio
from agent_advisory.equipment_patterns import has_specific_model_verified

class MockLLM:
    async def ask(self, messages, **kwargs):
        content = messages[0]['content']
        # Mock responses based on content
        if "1002" in content:
            return type('Response', (), {'content': 'yes'})()
        if "2000" in content:
            return type('Response', (), {'content': 'no'})()
        return type('Response', (), {'content': 'no'})()

async def test():
    print("=== Testing Tiered Model Detection ===")
    
    # 1. Structured Pattern (Tier 1 - No LLM)
    print(f"0312P (Expected True): {await has_specific_model_verified('Model 0312P specs')}")
    print(f"30XW-P (Expected True): {await has_specific_model_verified('30XW-P capacity')}")
    
    # 2. Contextual Rejection (Tier 2 - No LLM)
    print(f"Page 1002 (Expected False): {await has_specific_model_verified('See page 1002')}")
    print(f"Year 2024 (Expected False): {await has_specific_model_verified('Published in 2024')}")
    
    # 3. Ambiguous Fallback (Tier 3 - Calls LLM)
    llm = MockLLM()
    # '1002' matches bare 4-digit -> LLM says 'yes'
    print(f"Model 1002 (Expected True from LLM): {await has_specific_model_verified('Analysis of 1002', llm=llm)}")
    
    # '2000' matches bare 4-digit -> LLM says 'no'
    print(f"2000 units (Expected False from LLM): {await has_specific_model_verified('Order 2000 units', llm=llm)}")
    
    # 4. Ambiguous without LLM (Fallback to Accept)
    print(f"Model 1002 No LLM (Expected True default): {await has_specific_model_verified('Analysis of 1002', llm=None)}")

if __name__ == "__main__":
    asyncio.run(test())
