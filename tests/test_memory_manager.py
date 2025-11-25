import unittest
import shutil
import time
from pathlib import Path
from agent_cognitive.memory_manager import MemoryManager

TEST_DB_PATH = Path("data/test_memory/events.db")

class TestMemoryManager(unittest.TestCase):
    def setUp(self):
        # Clean up before test
        if TEST_DB_PATH.parent.exists():
            shutil.rmtree(TEST_DB_PATH.parent)
        
        self.memory = MemoryManager(db_path=TEST_DB_PATH)

    def tearDown(self):
        # Clean up after test
        if TEST_DB_PATH.parent.exists():
            shutil.rmtree(TEST_DB_PATH.parent)

    def test_add_and_retrieve_event(self):
        event = {
            "type": "test_event",
            "source": "unit_test",
            "payload": {"message": "hello world"},
            "timestamp": time.time()
        }
        
        row_id = self.memory.add_event(event)
        self.assertIsNotNone(row_id)
        
        events = self.memory.get_recent_events(limit=1)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["payload"]["message"], "hello world")

    def test_retention_policy(self):
        # Add old event (100 days ago)
        old_ts = time.time() - (100 * 86400)
        self.memory.add_event({
            "type": "old_event",
            "timestamp": old_ts,
            "payload": {}
        })
        
        # Add new event
        self.memory.add_event({
            "type": "new_event",
            "timestamp": time.time(),
            "payload": {}
        })
        
        # Run retention (assuming default is 90 days)
        self.memory.enforce_retention_policy()
        
        # Verify only new event remains
        events = self.memory.get_recent_events(limit=10)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "new_event")

    def test_gdpr_export_delete(self):
        user_id = "user_123"
        self.memory.add_event({
            "type": "user_action",
            "payload": {"user_id": user_id, "action": "login"}
        })
        self.memory.add_event({
            "type": "system_action",
            "payload": {"system": "boot"}
        })
        
        # Test Export
        data = self.memory.export_user_data(user_id)
        self.assertEqual(len(data["events"]), 1)
        self.assertEqual(data["events"][0]["payload"]["user_id"], user_id)
        
        # Test Delete
        deleted_count = self.memory.delete_user_data(user_id)
        self.assertEqual(deleted_count, 1)
        
        # Verify deletion
        events = self.memory.get_recent_events(limit=10)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "system_action")

if __name__ == "__main__":
    unittest.main()
