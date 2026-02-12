"""
Practical ARVIS Integration Test
=================================

End-to-end test demonstrating the full RAG pipeline with the ingested
Carrier 30XW chiller manual. Simulates realistic technician scenarios.

This test:
1. Re-ingests the 30XW manual (if needed)
2. Tests retrieval with realistic HVAC technician queries
3. Uses ARVIS Advisory system for recommendations
4. Demonstrates the full knowledge-grounded response pipeline
"""

import asyncio
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

# Ensure ARVIS modules are importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent_advisory.manual_ingester import ManualIngester, IngestionResult
from agent_advisory.knowledge_base import TechnicalKnowledgeBase, GraphRAGNavigator
from agent_advisory.building_aliases import check_topic_coverage, expand_query
from agent_advisory.response_modes import build_rag_prompt
from agent_unified.llm import UnifiedLLM

# ============================================================================
# TEST CONFIGURATION
# ============================================================================
MANUAL_PATH = Path("e:/Automation/30XW_tcm177-84440.pdf")
EQUIPMENT_ID = "30XW-CHILLER"
PERSIST_DIR = "data/test_30xw_kb"

# Scenarios matching the 30XW DATASHEET content
# (Performance data, electrical specs, dimensions - NOT service procedures)
HVAC_SCENARIOS = [
    {
        "name": "Cooling Capacity Query",
        "query": "What is the cooling capacity and COP for the 30XW chiller models?",
        "context": "Need to verify chiller sizing for building load",
        "expected_topics": ["capacity", "COP", "cooling"]
    },
    {
        "name": "Compressor Specifications",
        "query": "What type of compressors are used in the 30XW and what are their features?",
        "context": "Understanding compressor technology for maintenance planning",
        "expected_topics": ["compressor", "screw", "feature"]
    },
    {
        "name": "Water Flow Rates",
        "query": "What are the evaporator and condenser water flow rates for the 30XW?",
        "context": "Need flow data for pump sizing",
        "expected_topics": ["flow", "evaporator", "condenser"]
    },
    {
        "name": "Electrical Requirements",
        "query": "What are the electrical parameters and power requirements for the 30XW?",
        "context": "Planning electrical infrastructure for installation",
        "expected_topics": ["electrical", "power", "voltage"]
    },
    {
        "name": "Control System",
        "query": "What control system does the 30XW use and what are its features?",
        "context": "Understanding BMS integration options",
        "expected_topics": ["control", "Touch", "Pilot"]
    }
]


class ARVISIntegrationTest:
    """Full integration test with ARVIS capabilities."""
    
    def __init__(self, persist_dir: str = PERSIST_DIR):
        self.persist_dir = persist_dir
        self.kb = TechnicalKnowledgeBase(persist_directory=persist_dir)
        self.llm = UnifiedLLM()
        self.results: List[Dict] = []
        
    async def ensure_manual_ingested(self) -> IngestionResult:
        """Ensure the 30XW manual is ingested into the knowledge base."""
        print("\n" + "=" * 70)
        print("PHASE 1: DOCUMENT INGESTION")
        print("=" * 70)
        
        if not MANUAL_PATH.exists():
            raise FileNotFoundError(f"Manual not found: {MANUAL_PATH}")
        
        print(f"📄 Manual: {MANUAL_PATH.name}")
        print(f"🔧 Equipment ID: {EQUIPMENT_ID}")
        
        ingester = ManualIngester(self.kb)
        result = await ingester.ingest_pdf(
            str(MANUAL_PATH),
            equipment_id=EQUIPMENT_ID,
            include_tree_in_result=True
        )
        
        print(f"\n✅ Ingestion Complete:")
        print(f"   - Nodes indexed: {result.nodes_indexed}")
        print(f"   - Time: {result.ingestion_time_seconds:.1f}s")
        print(f"   - Description: {result.doc_description[:100]}...")
        
        if result.tree_structure:
            print(f"\n📑 Document Structure ({len(result.tree_structure)} sections):")
            for section in result.tree_structure[:8]:
                print(f"   [{section.get('start_index', '?')}-{section.get('end_index', '?')}] {section.get('title', 'Untitled')}")
        
        return result
    
    async def test_scenario(self, scenario: Dict) -> Dict:
        """Test a single HVAC scenario against the knowledge base."""
        print(f"\n{'─' * 60}")
        print(f"🔍 Scenario: {scenario['name']}")
        print(f"   Context: {scenario['context']}")
        print(f"   Query: {scenario['query']}")
        
        start_time = datetime.now()
        
        # 1. Query the knowledge base
        try:
            kb_results = await self.kb.query_specs(
                scenario["query"],
                equipment_id=EQUIPMENT_ID,
                limit=5
            )
        except Exception as e:
            kb_results = []
            print(f"   ⚠️ KB query error: {e}")
        
        retrieval_time = (datetime.now() - start_time).total_seconds()
        
        # 2. Analyze results
        result = {
            "scenario": scenario["name"],
            "query": scenario["query"],
            "retrieved_count": len(kb_results),
            "retrieval_time_ms": int(retrieval_time * 1000),
            "relevant_snippets": [],
            "topic_coverage": {},
            "success": False
        }
        
        if kb_results:
            print(f"\n   📚 Retrieved {len(kb_results)} relevant snippets:")
            for i, snippet in enumerate(kb_results[:3], 1):
                content = snippet.get("content", snippet.get("document", ""))[:150]
                distance = snippet.get("distance", 0)
                print(f"   {i}. [{distance:.3f}] {content}...")
                result["relevant_snippets"].append({
                    "content": content,
                    "distance": distance
                })
            
            # Check topic coverage with synonym expansion
            all_content = " ".join([s.get("content", s.get("document", "")).lower() for s in kb_results])
            result["topic_coverage"] = check_topic_coverage(all_content, scenario["expected_topics"])
            
            coverage_pct = sum(result["topic_coverage"].values()) / len(scenario["expected_topics"]) * 100
            result["coverage_percentage"] = coverage_pct
            result["success"] = coverage_pct >= 50  # At least 50% topic coverage
            
            print(f"\n   📊 Topic Coverage: {coverage_pct:.0f}%")
            for topic, found in result["topic_coverage"].items():
                icon = "✅" if found else "❌"
                print(f"      {icon} {topic}")
        else:
            print(f"   ❌ No results retrieved")
            result["coverage_percentage"] = 0
        
        # 3. Generate ARVIS response (if we have context)
        if kb_results:
            print(f"\n   🤖 Generating ARVIS Response...")
            try:
                context = "\n\n".join([s.get("content", s.get("document", ""))[:500] for s in kb_results[:3]])
                
                # Build prompt using engineering judgment scaffolding
                prompt = build_rag_prompt(
                    query=scenario['query'],
                    context=context,
                    equipment_name="Carrier 30XW chiller"
                )
                
                response = await self.llm.ask([
                    {"role": "user", "content": prompt}
                ])
                
                arvis_response = response.content if response.content else "No response generated"
                result["arvis_response"] = arvis_response[:500]
                print(f"\n   💬 ARVIS: {arvis_response[:300]}...")
                
            except Exception as e:
                print(f"   ⚠️ ARVIS response error: {e}")
                result["arvis_response"] = f"Error: {e}"
        
        return result
    
    async def run_all_scenarios(self) -> Dict:
        """Run all test scenarios and generate a report."""
        print("\n" + "=" * 70)
        print("PHASE 2: SCENARIO TESTING")
        print("=" * 70)
        
        for scenario in HVAC_SCENARIOS:
            result = await self.test_scenario(scenario)
            self.results.append(result)
        
        # Generate summary
        return self.generate_report()
    
    def generate_report(self) -> Dict:
        """Generate a summary report of all test results."""
        print("\n" + "=" * 70)
        print("PHASE 3: TEST REPORT")
        print("=" * 70)
        
        total = len(self.results)
        passed = sum(1 for r in self.results if r.get("success", False))
        avg_retrieval = sum(r.get("retrieval_time_ms", 0) for r in self.results) / total if total else 0
        avg_coverage = sum(r.get("coverage_percentage", 0) for r in self.results) / total if total else 0
        
        report = {
            "total_scenarios": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": f"{passed/total*100:.0f}%" if total else "N/A",
            "avg_retrieval_time_ms": int(avg_retrieval),
            "avg_topic_coverage": f"{avg_coverage:.0f}%",
            "results": self.results
        }
        
        print(f"\n📊 SUMMARY:")
        print(f"   Total Scenarios: {total}")
        print(f"   Passed: {passed} ({report['pass_rate']})")
        print(f"   Failed: {total - passed}")
        print(f"   Avg Retrieval Time: {avg_retrieval:.0f}ms")
        print(f"   Avg Topic Coverage: {avg_coverage:.0f}%")
        
        print(f"\n📋 INDIVIDUAL RESULTS:")
        for r in self.results:
            icon = "✅" if r.get("success") else "❌"
            print(f"   {icon} {r['scenario']}: {r.get('coverage_percentage', 0):.0f}% coverage, {r.get('retrieved_count', 0)} snippets")
        
        if passed == total:
            print(f"\n🎉 ALL TESTS PASSED!")
        elif passed >= total * 0.8:
            print(f"\n✅ MOSTLY PASSING - {total - passed} scenario(s) need attention")
        else:
            print(f"\n⚠️ NEEDS IMPROVEMENT - Only {passed}/{total} scenarios passed")
        
        return report


async def main():
    """Run the full integration test."""
    print("╔" + "═" * 68 + "╗")
    print("║" + " ARVIS PRACTICAL INTEGRATION TEST ".center(68) + "║")
    print("║" + " Carrier 30XW Chiller Manual RAG Pipeline ".center(68) + "║")
    print("╚" + "═" * 68 + "╝")
    
    test = ARVISIntegrationTest()
    
    # Phase 1: Ingest
    await test.ensure_manual_ingested()
    
    # Phase 2: Test scenarios
    report = await test.run_all_scenarios()
    
    print("\n" + "=" * 70)
    print("TEST COMPLETE")
    print("=" * 70)
    
    return report


if __name__ == "__main__":
    # Set environment variables if not already set
    if not os.getenv("LLM_PROVIDER"):
        os.environ["LLM_PROVIDER"] = "groq"
    
    report = asyncio.run(main())
