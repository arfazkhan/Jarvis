"""
Pipeline State Manager
---------------------
Thread-safe state management for async voice pipeline.

Handles:
- Queue management (audio, text)
- Interrupt vs Shutdown events
- Echo gating with debounce
- Pipeline flush on interruption
"""

import time
import threading
from queue import Queue, Empty

class ArvisState:
    """Central state manager for the voice pipeline."""
    
    def __init__(self):
        # === Queues ===
        self.text_stream = Queue()      # Tokens from LLM -> Sentinel
        self.audio_queue = Queue()      # PCM chunks -> Player
        self.tool_queue = Queue()       # Detected tool calls -> Executor
        
        # === Events ===
        # shutdown_event: Kills threads (app exit)
        # interrupt_event: Signals workers to discard current work but keep running
        self.shutdown_event = threading.Event()
        self.interrupt_event = threading.Event()
        
        # === Speaking State ===
        self.is_speaking = False
        self.last_speech_end_time = 0.0
        self._state_lock = threading.Lock()
        
        # === Echo Gate Config ===
        self.echo_debounce_ms = 300  # Wait 300ms after speech to re-enable VAD
        
        # === Sentinel Buffer ===
        self.sentinel_buffer = ""
        self.sentinel_lock = threading.Lock()
    
    # ==========================================
    # Speaking State (Thread-Safe)
    # ==========================================
    
    def set_speaking(self, value: bool):
        """Thread-safe setter for is_speaking."""
        with self._state_lock:
            self.is_speaking = value
            if not value:
                # Just stopped speaking - record time for debounce
                self.last_speech_end_time = time.time()
    
    def should_listen(self) -> bool:
        """
        Echo Gate with Debounce.
        
        Returns False if:
        - Currently speaking
        - Within 300ms of speech ending (reverb protection)
        """
        with self._state_lock:
            if self.is_speaking:
                return False
            
            # Debounce: Wait after speech ends
            elapsed = time.time() - self.last_speech_end_time
            if elapsed < (self.echo_debounce_ms / 1000.0):
                return False
            
            return True
    
    # ==========================================
    # Interrupt Handling
    # ==========================================
    
    def trigger_interrupt(self):
        """
        Called when user interrupts ARVIS mid-speech.
        
        1. Sets interrupt event
        2. Flushes all queues
        3. Clears sentinel buffer
        """
        self.interrupt_event.set()
        self.flush_queues()
        self.clear_sentinel_buffer()
        # Clear interrupt event after flush (workers can resume)
        self.interrupt_event.clear()
    
    def flush_queues(self):
        """Purge all audio and text queues."""
        # Drain audio queue
        while True:
            try:
                self.audio_queue.get_nowait()
            except Empty:
                break
        
        # Drain text stream
        while True:
            try:
                self.text_stream.get_nowait()
            except Empty:
                break
        
        # Drain tool queue
        while True:
            try:
                self.tool_queue.get_nowait()
            except Empty:
                break
    
    def clear_sentinel_buffer(self):
        """Clear the sentinel's text accumulation buffer."""
        with self.sentinel_lock:
            self.sentinel_buffer = ""
    
    # ==========================================
    # Shutdown
    # ==========================================
    
    def shutdown(self):
        """Clean shutdown of all pipeline threads."""
        self.shutdown_event.set()
        self.flush_queues()
    
    def is_running(self) -> bool:
        """Check if pipeline should continue running."""
        return not self.shutdown_event.is_set()
    
    def is_interrupted(self) -> bool:
        """Check if current work should be discarded."""
        return self.interrupt_event.is_set()


# === Singleton Instance ===
# All pipeline workers share this state
_arvis_state = None

def get_state() -> ArvisState:
    """Get the global ArvisState singleton."""
    global _arvis_state
    if _arvis_state is None:
        _arvis_state = ArvisState()
    return _arvis_state

def reset_state():
    """Reset state (for testing)."""
    global _arvis_state
    if _arvis_state:
        _arvis_state.shutdown()
    _arvis_state = ArvisState()
