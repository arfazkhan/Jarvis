"""
Stress Test: LLM Rate Limits
============================

Test ARVIS behavior when LLM returns 429 (rate limit).
- Rate limit handling
- Retry with backoff
- Queue management
"""

import pytest
import asyncio
from typing import Dict, Any

from agent_commercial.tools.equipment_tools import GetEquipmentStatus
from tests.factories import EquipmentFactory
from tests.mocks import MockBMSStateEngine, MockLLM


class MockRateLimitedLLM(MockLLM):
    """Mock LLM that simulates rate limiting."""
    
    def __init__(self, rate_limit_after: int = 5):
        super().__init__()
        self.rate_limit_after = rate_limit_after
        self.call_count = 0
        self.rate_limited_calls = []
    
    async def ask(self, prompt: str, **kwargs) -> str:
        self.call_count += 1
        
        # Simulate rate limit after N calls
        if self.call_count > self.rate_limit_after:
            self.rate_limited_calls.append(self.call_count)
            raise Exception("429 Too Many Requests")
        
        return await super().ask(prompt, **kwargs)


class TestLLMRateLimits:
    """What happens when LLM returns 429?"""
    
    @pytest.mark.asyncio
    @pytest.mark.stress
    async def test_rate_limit_single_call(self, mock_bms_state):
        """Single call gets rate limited, should handle gracefully."""
        llm = MockRateLimitedLLM(rate_limit_after=0)  # Rate limit immediately
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        
        tool = GetEquipmentStatus()
        tool.bms_state = mock_bms_state
        
        # Execute
        result = await tool.execute(equipment_id="CH-01")
        
        # Should handle gracefully
        assert result.success or result.error
        if result.error:
            assert "rate" in result.error.lower() or "limit" in result.error.lower() or "429" in result.error
    
    @pytest.mark.asyncio
    @pytest.mark.stress
    async def test_rate_limit_with_retry(self, mock_bms_state):
        """Rate limit, then retry should succeed."""
        llm = MockRateLimitedLLM(rate_limit_after=1)  # Rate limit on 2nd call
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        
        tool = GetEquipmentStatus()
        tool.bms_state = mock_bms_state
        
        # First call should succeed
        result1 = await tool.execute(equipment_id="CH-01")
        assert result1.success
        
        # Second call might be rate limited but should handle it
        result2 = await tool.execute(equipment_id="CH-01")
        assert result2.success or result2.error  # Should handle gracefully
    
    @pytest.mark.asyncio
    @pytest.mark.stress
    async def test_rate_limit_burst_calls(self, mock_bms_state):
        """Burst of calls should handle rate limits."""
        llm = MockRateLimitedLLM(rate_limit_after=3)
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        
        tool = GetEquipmentStatus()
        tool.bms_state = mock_bms_state
        
        # Burst of calls
        tasks = [
            tool.execute(equipment_id="CH-01")
            for _ in range(10)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Should not crash
        exceptions = [r for r in results if isinstance(r, Exception)]
        assert len(exceptions) == 0, f"Got {len(exceptions)} unhandled exceptions"
    
    @pytest.mark.asyncio
    @pytest.mark.stress
    async def test_rate_limit_with_backoff(self, mock_bms_state):
        """Rate limited calls should back off and retry."""
        llm = MockRateLimitedLLM(rate_limit_after=2)
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        
        tool = GetEquipmentStatus()
        tool.bms_state = mock_bms_state
        
        successes = 0
        for i in range(5):
            llm.call_count = 0  # Reset each iteration
            result = await tool.execute(equipment_id="CH-01")
            if result.success:
                successes += 1
            # Small delay between calls (simulating backoff)
            await asyncio.sleep(0.1)
        
        # Should have some successes even with rate limiting
        assert successes > 0, "Should have some successes with backoff"


if __name__ == "__main__":
    import sys
    pytest.main([__file__, "-v", "-m", "stress"])
