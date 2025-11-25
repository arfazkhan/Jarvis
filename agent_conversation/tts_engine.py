"""
TTS Engine (Text-to-Speech)
---------------------------
Handles text-to-speech synthesis using pyttsx3 (offline).
"""

import threading
import queue
from typing import Optional

from config.settings import get_config

# Conditional import
try:
    import pyttsx3
    TTS_AVAILABLE = True
except ImportError:
    TTS_AVAILABLE = False

CONFIG = get_config("conversation")
TTS_CONFIG = CONFIG.get("tts", {})


class TTSEngine:
    def __init__(self):
        self.engine = None
        self.queue = queue.Queue()
        self.is_speaking = False
        
        if TTS_AVAILABLE:
            try:
                self.engine = pyttsx3.init()
                self._configure_engine()
                self._start_loop()
            except Exception as e:
                print(f"[TTSEngine] Error initializing pyttsx3: {e}")
        else:
            print("[TTSEngine] pyttsx3 not installed. TTS disabled.")

    def _configure_engine(self):
        """Apply configuration settings"""
        if not self.engine: return
        
        # Rate
        rate = TTS_CONFIG.get("rate", 150)
        self.engine.setProperty('rate', rate)
        
        # Volume
        volume = TTS_CONFIG.get("volume", 0.9)
        self.engine.setProperty('volume', volume)
        
        # Voice (optional: select first available female voice usually)
        voices = self.engine.getProperty('voices')
        # Simple heuristic: look for 'female' or 'zira' (windows)
        for voice in voices:
            if "zira" in voice.name.lower() or "female" in voice.name.lower():
                self.engine.setProperty('voice', voice.id)
                break

    def _start_loop(self):
        """Start the background thread for processing speech queue"""
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        """Process speech queue"""
        while True:
            text = self.queue.get()
            if text is None: break
            
            self.is_speaking = True
            try:
                print(f"[TTSEngine] Speaking: {text}")
                self.engine.say(text)
                self.engine.runAndWait()
            except Exception as e:
                print(f"[TTSEngine] Error speaking: {e}")
            finally:
                self.is_speaking = False
                self.queue.task_done()

    def speak(self, text: str, block: bool = False):
        """
        Speak the given text.
        If block=True, waits until speech is finished.
        """
        if not self.engine:
            print(f"[TTSEngine] (Mock) Speaking: {text}")
            return

        if block:
            # For blocking, we bypass the queue to run in current thread
            # NOTE: pyttsx3 runAndWait blocks the loop, so be careful
            try:
                self.engine.say(text)
                self.engine.runAndWait()
            except Exception as e:
                print(f"[TTSEngine] Error in blocking speak: {e}")
        else:
            self.queue.put(text)

    def stop(self):
        """Stop current speech and clear queue"""
        if self.engine:
            self.engine.stop()
        
        # Clear queue
        with self.queue.mutex:
            self.queue.queue.clear()
