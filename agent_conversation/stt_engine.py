"""
STT Engine (Speech-to-Text)
---------------------------
Handles audio capture and transcription using OpenAI Whisper (local).
Falls back to SpeechRecognition (Google/Sphinx) if Whisper is unavailable.
"""

import os
import time
import threading
import queue
from typing import Optional, Callable

from config.settings import get_config

# Conditional imports
try:
    import whisper
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False

try:
    import speech_recognition as sr
    SR_AVAILABLE = True
except ImportError:
    SR_AVAILABLE = False

CONFIG = get_config("conversation")
STT_CONFIG = CONFIG.get("stt", {})


class STTEngine:
    def __init__(self):
        self.model = None
        self.recognizer = None
        self.microphone = None
        self.listening = False
        self.audio_queue = queue.Queue()
        
        self._init_engine()

    def _init_engine(self):
        """Initialize the STT engine based on config and availability"""
        engine_type = STT_CONFIG.get("engine", "whisper")
        
        if engine_type == "whisper" and WHISPER_AVAILABLE:
            print(f"[STTEngine] Loading Whisper model: {STT_CONFIG.get('whisper_model', 'base')}...")
            try:
                self.model = whisper.load_model(STT_CONFIG.get("whisper_model", "base"))
                print("[STTEngine] Whisper model loaded.")
            except Exception as e:
                print(f"[STTEngine] Error loading Whisper: {e}. Falling back to SpeechRecognition.")
                self.model = None
        
        if SR_AVAILABLE:
            self.recognizer = sr.Recognizer()
            # Adjust energy threshold for ambient noise
            self.recognizer.energy_threshold = 300
            self.recognizer.dynamic_energy_threshold = True

    def listen_once(self, timeout: int = 5) -> str:
        """
        Listen for a single phrase and return text.
        Blocking call.
        """
        if not SR_AVAILABLE:
            return "Error: SpeechRecognition not installed"

        try:
            with sr.Microphone() as source:
                print("[STTEngine] Listening...")
                # self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio = self.recognizer.listen(source, timeout=timeout, phrase_time_limit=10)
                print("[STTEngine] Processing...")
                
                return self._transcribe(audio)
        except sr.WaitTimeoutError:
            return ""
        except Exception as e:
            print(f"[STTEngine] Error listening: {e}")
            return ""

    def _transcribe(self, audio_data) -> str:
        """Transcribe audio data using the best available engine"""
        
        # 1. Try Whisper
        if self.model and WHISPER_AVAILABLE:
            try:
                # Whisper expects raw audio or file path. 
                # SR audio_data needs conversion.
                # For simplicity/speed in MVP, we might save to temp file
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                    f.write(audio_data.get_wav_data())
                    temp_path = f.name
                
                result = self.model.transcribe(temp_path, fp16=False) # fp16=False for CPU
                os.remove(temp_path)
                
                text = result.get("text", "").strip()
                if text:
                    print(f"[STTEngine] Whisper heard: '{text}'")
                return text
            except Exception as e:
                print(f"[STTEngine] Whisper transcription failed: {e}")

        # 2. Fallback to Google Speech Recognition (Online)
        if self.recognizer:
            try:
                text = self.recognizer.recognize_google(audio_data)
                print(f"[STTEngine] Google heard: '{text}'")
                return text
            except sr.UnknownValueError:
                return ""
            except sr.RequestError as e:
                print(f"[STTEngine] Google API error: {e}")
                return ""

        return ""

    def start_background_listening(self, callback: Callable[[str], None]):
        """
        Start continuous listening in background.
        Calls callback(text) when speech is detected.
        """
        if not SR_AVAILABLE:
            print("[STTEngine] Cannot start background listening: SpeechRecognition missing")
            return

        self.listening = True
        
        def listener_thread():
            with sr.Microphone() as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=1)
                print("[STTEngine] Background listening started.")
                
                while self.listening:
                    try:
                        audio = self.recognizer.listen(source, timeout=1, phrase_time_limit=10)
                        text = self._transcribe(audio)
                        if text:
                            callback(text)
                    except sr.WaitTimeoutError:
                        continue
                    except Exception as e:
                        if self.listening:
                            print(f"[STTEngine] Background listen error: {e}")
                            time.sleep(1)

        threading.Thread(target=listener_thread, daemon=True).start()

    def stop_listening(self):
        self.listening = False
