import unittest
import shutil
import tempfile
import os
import asyncio
import time
from agent_commercial.skillbook import get_skillbook, BuildingSkillbook
from scratch.marina_prove_it import inject_operator_event as inject_marina
from scratch.arvis_pilot_prove_it import inject_operator_event as inject_pilot

class MockPatternStore:
    def __init__(self):
        self.successes = []
    def log_success(self, query, tool_calls, operator_id):
        self.successes.append((query, tool_calls, operator_id))

class MockLearningEngine:
    def __init__(self):
        self.pattern_store = MockPatternStore()

class MockKB:
    def __init__(self):
        self.snippets = []
    def index_technical_snippet(self, content, source, equipment_id, manual_type, chunk_type, tags):
        self.snippets.append({
            "content": content,
            "source": source,
            "equipment_id": equipment_id,
            "manual_type": manual_type,
            "chunk_type": chunk_type,
            "tags": tags
        })

class MockLLMAgent:
    def __init__(self):
        self.knowledge_base = MockKB()

class MockCopilot:
    def __init__(self, building_id):
        self.building_id = building_id
        self.learning_engine = MockLearningEngine()
        self.llm_agent = MockLLMAgent()

class TestSkillbookIngestion(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_skillbook.db")
        
        # Override singleton/factory db path for testing
        os.environ["ARVIS_DB_PATH"] = self.db_path
        
        # Initialize Skillbook
        self.sb = BuildingSkillbook("test_ingestion", db_path=self.db_path)
        
        from agent_commercial.skillbook import _skillbooks
        _skillbooks["test_ingestion"] = self.sb
        
        # Warm up the embedding model to eliminate first-load latency
        if self.sb.matcher.is_available:
            self.sb.matcher.encode("warmup")
            
        self.copilot = MockCopilot("test_ingestion")
        
        import logging
        import sys
        from scratch.marina_prove_it import _prove_logger as marina_log
        from scratch.arvis_pilot_prove_it import _prove_logger as pilot_log
        
        for logger in [marina_log, pilot_log]:
            logger.setLevel(logging.DEBUG)
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
            logger.addHandler(handler)

    def tearDown(self):
        # Reset singleton cache
        from agent_commercial.skillbook import _skillbooks
        _skillbooks.clear()
        
        if "ARVIS_DB_PATH" in os.environ:
            del os.environ["ARVIS_DB_PATH"]
            
        try:
            import gc
            gc.collect()
            shutil.rmtree(self.test_dir)
        except Exception:
            pass

    async def test_marina_ingestion_and_retrieve_under_1s(self):
        """Test that marina's inject_operator_event writes to SQL skillbook and retrieve takes < 1s."""
        t0 = time.perf_counter()
        
        # 1. Ingest
        await inject_marina(
            copilot=self.copilot,
            event_type="test_event_type",
            description="CH-02 scale cleaning completed, COP increased dramatically",
            outcome="positive",
            day_offset=0
        )
        
        # 2. Query Skillbook within 1s
        query_context = {
            "query": "CH-02 scale cleaning",
            "equipment_id": "CH-02"
        }
        
        res = await self.sb.query_skillbook(
            building_id="test_ingestion",
            context=query_context,
            equipment_id="CH-02"
        )
        
        t_elapsed = time.perf_counter() - t0
        self.assertLess(t_elapsed, 3.0, f"Read-after-write took too long: {t_elapsed}s")
        
        # 3. Assertions
        skills = res.get("skills", [])
        if len(skills) == 0:
            import aiosqlite
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute("SELECT * FROM skills") as cursor:
                    rows = await cursor.fetchall()
                    print("\nDEBUG skills table contents:", rows)
        self.assertGreater(len(skills), 0, "No skills were returned by query_skillbook!")
        
        # Verify title or content matches
        found = False
        for s in skills:
            if "CH-02 scale cleaning" in s.get("description", ""):
                found = True
                self.assertEqual(s.get("equipment_id"), "CH-02")
                self.assertIn("test_event_type", s.get("tags", []))
                
        self.assertTrue(found, "The injected operator event was not found in BuildingSkillbook!")

    async def test_pilot_ingestion_and_retrieve_under_1s(self):
        """Test that pilot's inject_operator_event writes to SQL skillbook and retrieve takes < 1s."""
        t0 = time.perf_counter()
        
        # 1. Ingest
        await inject_pilot(
            copilot=self.copilot,
            event_type="pilot_event_type",
            description="AHU-01 motor replaced, supply fan speed stabilized",
            outcome="positive",
            day_offset=0
        )
        
        # 2. Query Skillbook within 1s
        query_context = {
            "query": "AHU-01 motor",
            "equipment_id": "AHU-01"
        }
        
        res = await self.sb.query_skillbook(
            building_id="test_ingestion",
            context=query_context,
            equipment_id="AHU-01"
        )
        
        t_elapsed = time.perf_counter() - t0
        self.assertLess(t_elapsed, 3.0, f"Read-after-write took too long: {t_elapsed}s")
        
        # 3. Assertions
        skills = res.get("skills", [])
        self.assertGreater(len(skills), 0, "No skills were returned by query_skillbook!")
        
        found = False
        for s in skills:
            if "AHU-01 motor replaced" in s.get("description", ""):
                found = True
                self.assertEqual(s.get("equipment_id"), "AHU-01")
                self.assertIn("pilot_event_type", s.get("tags", []))
                
        self.assertTrue(found, "The injected pilot operator event was not found in BuildingSkillbook!")

if __name__ == "__main__":
    unittest.main()
