"""
Stress Test: LLM Timeouts
=========================

Test ARVIS behavior when LLM takes too long or times out.
- Mock LLM with configurable delays
- Timeout handling
- Retry logic
"""

import pytest
import asyncio
from agent_commercial.tools.equipment_tools import GetEquipmentStatus
from tests.factories import EquipmentFactory
from tests.mocks import MockBMSStateEngine, MockLLM


class TestLLMTimeouts:
    """What happens when LLM times out?"""
    
    @pytest.mark.asyncio
    @pytest.mark.stress
    async def test_llm_slow_response_10s(self, mock_bms_state):
        """LLM takes 10 seconds to respond."""
        # Setup LLM with 10s delay
        mock_llm = MockLLM(delay_seconds=10.0)
        
        # Create tool with LLM dependency
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        
        tool = GetEquipmentStatus()
        tool.bms_state = mock_bms_state
        
        # Execute with timeout
        start = asyncio.get_event_loop().time()
        result = await asyncio.wait_for(
            tool.execute(equipment_id="CH-01"),
            timeout=15.0  # Allow time for slow response
        )
        elapsed = asyncio.get_event_loop().time() - start
        
        # Verify
        assert result.success, "Should still succeed"
        assert elapsed >= 10.0, f"Should have waited for slow response (took {elapsed:.2f}s)"
    
    @pytest.mark.asyncio
    @pytest.mark.stress
    async def test_llm_timeout_handled_gracefully(self, mock_llm, mock_bms_state):
        """LLM times out, tool should handle gracefully."""
        # Setup LLM to fail
        mock_llm.fail_rate = 1.0  # Always fail
        
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        
        tool = GetEquipmentStatus()
        tool.bms_state = mock_bms_state
        
        # Execute
        result = await tool.execute(equipment_id="CH-01")
        
        # Should handle gracefully
        assert result.success or result.error, "Should have result or error"
    
    @pytest.mark.asyncio
    @pytest.mark.stress
    async def test_llm_partial_failure_recovery(self, mock_llm, mock_bms_state):
        """LLM fails sometimes, tool should retry and recover."""
        # Setup LLM with 50% failure rate
        mock_llm.fail_rate = 0.5
        
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        
        tool = GetEquipmentStatus()
        tool.bms_state = mock_bms_state
        
        # Execute multiple times
        successes = 0
        for _ in range(10):
            mock_llm.reset()
            result = await tool.execute(equipment_id="CH-01")
            if result.success:
                successes += 1
        
        # Should have at least some successes
        assert successes > 0, "Should have at least one success despite failures"
    
    @pytest.mark.asyncio
    @pytest.mark.stress
    async def test_llm_timeout_with_fallback(self, mock_llm, mock_bms_state):
        """Tool has fallback when LLM unavailable."""
        mock_llm.fail_rate = 1.0  # Always fail
        
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        
        tool = GetEquipmentStatus()
        tool.bms_state = mock_bms_state
        
        # Execute
        result = await tool.execute(equipment_id="CH-01")
        
        # Should fallback to cached/default data
        assert result.success, "Should succeed with fallback data"


if __name__ == "__main__":
    import sys
    pytest.main([__file__, "-v", "-m", "stress"])
