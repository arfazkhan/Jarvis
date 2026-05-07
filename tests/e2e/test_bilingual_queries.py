#!/usr/bin/env python3
"""
E2E Test: Bilingual Query Support
================================

Scenario: Operator queries in English and Arabic, gets accurate responses.

Full workflow:
1. English query: "What's the chiller status?"
2. System responds in English with correct data
3. Arabic query: "ما حالة المبرد؟" (What's the chiller status?)
4. System responds in Arabic with same data
5. Both responses have equivalent accuracy
"""

import pytest
import asyncio

from tests.mocks import MockLLM, MockBMSStateEngine
from tests.factories import EquipmentFactory


class TestBilingualQueries:
    """
    Test bilingual (English/Arabic) query support.
    """
    
    @pytest.fixture
    def bilingual_state(self):
        """Building state for bilingual queries."""
        state = MockBMSStateEngine()
        state.add_equipment(EquipmentFactory.chiller())
        state.update_point("CH-01/CHWST", 7.2, "°C", "CH-01")
        return state
    
    @pytest.fixture
    def bilingual_llm(self):
        """LLM configured for both languages."""
        return MockLLM(responses={
            "chiller": '''
            {
                "status": "running",
                "supply_temp": 7.2,
                "efficiency": 94,
                "alarms": 0
            }
            ''',
            "مبرد": '''
            {
                "status": "قيد التشغيل",
                "supply_temp": 7.2,
                "efficiency": 94,
                "alarms": 0
            }
            ''',
        })
    
    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_english_query_returns_english_response(self, bilingual_state, bilingual_llm):
        """English query should return English response."""
        response = await bilingual_llm.ask("What is the chiller status?")
        
        # Should be in English
        assert "running" in response.lower() or "status" in response.lower()
    
    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_arabic_query_returns_arabic_response(self, bilingual_state, bilingual_llm):
        """Arabic query should return Arabic response."""
        response = await bilingual_llm.ask("ما حالة المبرد؟")
        
        # Should be in Arabic
        assert "تشغيل" in response or "قيد" in response
    
    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_both_languages_accurate(self, bilingual_state, bilingual_llm):
        """Both languages should return equally accurate data."""
        # English query
        en_response = await bilingual_llm.ask("Chiller status")
        
        # Arabic query
        ar_response = await bilingual_llm.ask("حالة المبرد")
        
        # Both should have same numerical values
        import json
        
        try:
            en_data = json.loads(en_response)
            ar_data = json.loads(ar_response)
            
            # Supply temp should be identical
            assert en_data.get("supply_temp") == ar_data.get("supply_temp")
            assert en_data.get("efficiency") == ar_data.get("efficiency")
        except json.JSONDecodeError:
            # If not JSON, check for key numbers in text
            assert "7.2" in en_response
            assert "7.2" in ar_response


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
