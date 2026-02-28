"""
Verification Script for Memory System Retention & Retrieval
===========================================================
This script validates that the MemoryOrchestrator can:
1. Initialize the memory stores (ChromaDB/SQLite)
2. Persist new memories (Preferences & Observations)
3. Recall memories using semantic/keyword search
4. Clean up test data
"""

import os
import sys
import shutil
import logging
from pathlib import Path
from colorama import init, Fore, Style

# Ensure environment is set up
sys.path.append(os.getcwd())
init()

import gc
import time
from arvis_core.memory.orchestrator import MemoryOrchestrator

# Configure Logging
# Enable INFO logs for agent.memory to see initialization status (Chroma vs Fallback)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("verify_memory")

TEST_DIR = "tests_data/memory_verification"

def print_header(title):
    print(f"\n{Fore.CYAN}=== {title} ==={Style.RESET_ALL}")

def verify_memory_system():
    print_header("Initializing Memory System")
    
    # Clean previous run
    if os.path.exists(TEST_DIR):
        shutil.rmtree(TEST_DIR)
        
    try:
        # 1. Initialize
        memory = MemoryOrchestrator(persist_dir=TEST_DIR)
        print(f"{Fore.GREEN}✓ MemoryOrchestrator initialized at {TEST_DIR}{Style.RESET_ALL}")
        
        # 2. Store Data
        print_header("Storing Test Memories")
        
        # Preference: "User likes office temp at 23C"
        pref_id = memory.remember(
            content="User prefers office temperature to be 23 degrees Celsius",
            memory_type="preference",
            key="office_temp",
            context="climate",
            importance=0.9
        )
        print(f"  > Stored Preference: 'User prefers office temperature to be 23 degrees Celsius' (ID: {pref_id})")
        
        # Observation: "Meeting room occupancy is high on Mondays"
        obs_id = memory.remember(
            content="Meeting room occupancy is consistently high on Monday mornings",
            memory_type="observation",
            context="occupancy",
            importance=0.6,
            source="sensor_analysis"
        )
        print(f"  > Stored Observation: 'Meeting room occupancy is consistently high on Monday mornings' (ID: {obs_id})")
        
        # 3. Retrieve Data
        print_header("Testing Retrieval (Recall)")
        
        # Wait for ChromaDB indexing
        print("  [Wait] Allowing 2s for Vector Indexing...")
        time.sleep(2)
        
        # Query 1: Temperature Preference (Semantic)
        query1 = "What is the preferred office temperature?"
        results1 = memory.recall(query1, memory_type="preferences")
        
        print(f"  Q: '{query1}'")
        if results1 and "23" in results1[0]['content']:
            print(f"{Fore.GREEN}  ✓ MATCH: {results1[0]['content']} (Score: {results1[0].get('score', 'N/A')}){Style.RESET_ALL}")
        else:
             print(f"{Fore.RED}  ✗ FAILED: Retrieved {results1}{Style.RESET_ALL}")
             return False

        # Query 2: Occupancy Observation
        # Note: ObservationStore uses simple substring matching (LIKE %query%), so we need a keyword that exists in the text.
        query2 = "occupancy"
        results2 = memory.recall(query2, memory_type="observations")
        
        print(f"  Q: '{query2}'")
        if results2 and "Monday" in results2[0]['content']:
            print(f"{Fore.GREEN}  ✓ MATCH: {results2[0]['content']} (Score: {results2[0].get('score', 'N/A')}){Style.RESET_ALL}")
        else:
            print(f"{Fore.RED}  ✗ FAILED: Retrieved {results2}{Style.RESET_ALL}")
            return False
            
        print_header("Verification Result")
        print(f"{Fore.GREEN}SUCCESS: Memory system is retrieving and remembering correctly.{Style.RESET_ALL}")
        return True

    except Exception as e:
        print(f"\n{Fore.RED}CRITICAL FAILURE: {e}{Style.RESET_ALL}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        # Cleanup with retry logic for Windows file locks
        if os.path.exists(TEST_DIR):
            print(f"\n{Fore.YELLOW}[Cleanup] Attempting to remove test data at {TEST_DIR}...{Style.RESET_ALL}")
            
            # Force garbage collection to release file handles
            del memory
            gc.collect()
            time.sleep(1.0)
            
            max_retries = 3
            for i in range(max_retries):
                try:
                    shutil.rmtree(TEST_DIR)
                    print(f"{Fore.GREEN}[Cleanup] Successfully removed test data.{Style.RESET_ALL}")
                    break
                except PermissionError:
                    if i < max_retries - 1:
                        print(f"{Fore.YELLOW}[Cleanup] File locked. Retrying ({i+1}/{max_retries})...{Style.RESET_ALL}")
                        time.sleep(2.0)
                    else:
                         print(f"{Fore.RED}[Cleanup Warning] Could not delete {TEST_DIR} due to file locks. Manual cleanup required.{Style.RESET_ALL}")
                except Exception as e:
                    print(f"{Fore.RED}[Cleanup Error] {e}{Style.RESET_ALL}")
                    break

if __name__ == "__main__":
    success = verify_memory_system()
    sys.exit(0 if success else 1)
