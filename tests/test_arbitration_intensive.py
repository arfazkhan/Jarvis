import unittest
import threading
import time
import random
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agent_home.agent_core.arbitration_manager import ArbitrationManager, Priority

class TestArbitrationIntensive(unittest.TestCase):
    def setUp(self):
        self.arbiter = ArbitrationManager()

    def test_priority_preemption(self):
        """Verify strict priority enforcement."""
        dev = "light_1"
        
        # 1. Low priority grabs lock
        self.assertTrue(self.arbiter.request_lock(dev, "Auto", Priority.AUTOMATION_RULE))
        
        # 2. Medium priority preempts
        self.assertTrue(self.arbiter.request_lock(dev, "Mission", Priority.MISSION_EXECUTION))
        status = self.arbiter.get_lock_status(dev)
        self.assertEqual(status["source"], "Mission")
        
        # 3. High priority preempts
        self.assertTrue(self.arbiter.request_lock(dev, "User", Priority.USER_COMMAND))
        status = self.arbiter.get_lock_status(dev)
        self.assertEqual(status["source"], "User")
        
        # 4. Low priority DENIED
        self.assertFalse(self.arbiter.request_lock(dev, "Auto2", Priority.AUTOMATION_RULE))

    def test_lock_expiration(self):
        """Verify locks expire correctly."""
        dev = "light_2"
        self.arbiter.request_lock(dev, "User", Priority.USER_COMMAND, duration=0.1)
        
        # Should be locked
        self.assertIsNotNone(self.arbiter.get_lock_status(dev))
        
        # Wait for expiry
        time.sleep(0.15)
        
        # Should be free (or takable)
        self.assertIsNone(self.arbiter.get_lock_status(dev))
        
        # Low priority can now take it
        self.assertTrue(self.arbiter.request_lock(dev, "Auto", Priority.AUTOMATION_RULE))

    def test_concurrency_stress(self):
        """Aggressive concurrency test with multiple threads fighting for locks."""
        devices = [f"dev_{i}" for i in range(10)]
        sources = ["User", "Mission", "Auto", "Safety"]
        priorities = [Priority.USER_COMMAND, Priority.MISSION_EXECUTION, Priority.AUTOMATION_RULE, Priority.SAFETY_LOCK]
        
        stop_event = threading.Event()
        errors = []
        
        def worker(worker_id):
            while not stop_event.is_set():
                dev = random.choice(devices)
                src_idx = random.randint(0, 3)
                src = f"{sources[src_idx]}_{worker_id}"
                prio = priorities[src_idx]
                
                try:
                    # Randomly request or release
                    if random.random() < 0.7:
                        self.arbiter.request_lock(dev, src, prio, duration=0.05)
                    else:
                        self.arbiter.release_lock(dev, src)
                except Exception as e:
                    errors.append(e)
                    
        threads = []
        for i in range(20): # 20 threads hammering 10 devices
            t = threading.Thread(target=worker, args=(i,))
            t.start()
            threads.append(t)
            
        time.sleep(2.0) # Run for 2 seconds
        stop_event.set()
        
        for t in threads:
            t.join()
            
        self.assertEqual(len(errors), 0, f"Concurrency errors found: {errors}")
        print(f"\n[Stress] Concurrency test passed with 20 threads.")

    def test_fuzzing_priorities(self):
        """Fuzzing test with random priorities and durations."""
        dev = "fuzz_dev"
        current_owner = None
        current_prio = -1
        
        for i in range(1000):
            prio = random.choice(list(Priority))
            src = f"src_{i}"
            duration = random.uniform(0.001, 0.01)
            
            success = self.arbiter.request_lock(dev, src, prio, duration)
            
            status = self.arbiter.get_lock_status(dev)
            
            if success:
                # If we succeeded, we must be higher/equal priority OR lock expired
                if status:
                    self.assertEqual(status["source"], src)
            else:
                # If we failed, current lock must be higher/equal
                if status:
                    self.assertGreaterEqual(status["priority"], prio)

        print(f"\n[Fuzz] 1000 random lock requests processed correctly.")

if __name__ == "__main__":
    unittest.main()
