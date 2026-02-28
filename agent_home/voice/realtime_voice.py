"""
Unified RealtimeSTT + RealtimeTTS wrapper for ARVIS voice pipeline.

Provides a simplified interface combining:
- Wake word detection (Porcupine via RealtimeSTT)
- Voice activity detection (Silero VAD via RealtimeSTT)
- Real-time transcription (faster-whisper via RealtimeSTT)
- Streaming TTS playback (CoquiEngine via RealtimeTTS)
"""

import logging
import threading
from typing import Callable, Optional, Generator

logger = logging.getLogger(__name__)


class RealtimeVoice:
    """
    Unified voice interface wrapping RealtimeSTT and RealtimeTTS.
    
    Usage:
        voice = RealtimeVoice(on_transcription=handle_text)
        voice.start()
        
        # Speak with streaming support
        voice.speak("Hello world")
        voice.speak_stream(token_generator)
        
        voice.stop()
    """
    
    def __init__(
        self,
        on_transcription: Optional[Callable[[str], None]] = None,
        wake_words: list[str] = None,
        tts_engine: str = "coqui",  # "coqui", "kokoro", or "piper"
        model_size: str = "base",   # Whisper model size
    ):
        """
        Initialize the voice pipeline.
        
        Args:
            on_transcription: Callback when transcription is complete
            wake_words: Wake words to listen for (None = always listening)
            tts_engine: TTS engine to use
            model_size: Whisper model size for STT
        """
        self._on_transcription = on_transcription
        self._wake_words = wake_words or []
        self._tts_engine_name = tts_engine
        self._model_size = model_size
        
        self._recorder = None
        self._tts_stream = None
        self._tts_engine = None
        self._running = False
        self._listen_thread = None
        
    def start(self):
        """Initialize and start the voice pipeline."""
        if self._running:
            logger.warning("RealtimeVoice already running")
            return
            
        logger.info("Starting RealtimeVoice pipeline...")
        
        # Initialize TTS engine
        self._init_tts()
        
        # Initialize STT recorder
        self._init_stt()
        
        self._running = True
        logger.info("RealtimeVoice pipeline started")
        
    def _init_tts(self):
        """Initialize the TTS engine and stream."""
        from RealtimeTTS import TextToAudioStream
        
        if self._tts_engine_name == "coqui":
            from RealtimeTTS import CoquiEngine
            self._tts_engine = CoquiEngine()
        elif self._tts_engine_name == "kokoro":
            from RealtimeTTS import KokoroEngine
            self._tts_engine = KokoroEngine()
        elif self._tts_engine_name == "piper":
            from RealtimeTTS import PiperEngine
            self._tts_engine = PiperEngine()
        else:
            raise ValueError(f"Unknown TTS engine: {self._tts_engine_name}")
            
        self._tts_stream = TextToAudioStream(
            self._tts_engine,
            on_audio_stream_start=self._on_tts_start,
            on_audio_stream_stop=self._on_tts_stop,
        )
        
        # Prewarm the engine
        logger.info(f"Prewarming {self._tts_engine_name} TTS engine...")
        self._tts_stream.feed(".")
        self._tts_stream.play(muted=True)
        logger.info("TTS engine ready")
        
    def _init_stt(self):
        """Initialize the STT recorder."""
        from RealtimeSTT import AudioToTextRecorder
        
        recorder_config = {
            "model": self._model_size,
            "language": "en",
            "compute_type": "float16",  # GPU acceleration
            "silero_sensitivity": 0.4,
            "webrtc_sensitivity": 2,
            "post_speech_silence_duration": 0.4,
            "min_length_of_recording": 0.5,
            "min_gap_between_recordings": 0,
            "enable_realtime_transcription": True,
            "realtime_processing_pause": 0.1,
            "on_realtime_transcription_update": self._on_realtime_update,
        }
        
        # Add wake word config if specified
        if self._wake_words:
            recorder_config["wake_words"] = ",".join(self._wake_words)
            recorder_config["wake_word_activation_delay"] = 0.3
            
        self._recorder = AudioToTextRecorder(**recorder_config)
        logger.info(f"STT recorder initialized with model '{self._model_size}'")
        
    def _on_tts_start(self):
        """Called when TTS playback starts."""
        logger.debug("TTS playback started")
        
    def _on_tts_stop(self):
        """Called when TTS playback stops."""
        logger.debug("TTS playback stopped")
        
    def _on_realtime_update(self, text: str):
        """Called with real-time transcription updates."""
        logger.debug(f"Realtime transcription: {text}")
        
    def listen(self) -> str:
        """
        Block and listen for speech, return transcription.
        
        Returns:
            Transcribed text from user speech
        """
        if not self._running or not self._recorder:
            raise RuntimeError("RealtimeVoice not started")
            
        logger.debug("Listening for speech...")
        text = self._recorder.text()
        logger.info(f"Transcribed: {text}")
        
        if self._on_transcription:
            self._on_transcription(text)
            
        return text
        
    def listen_loop(self, callback: Optional[Callable[[str], None]] = None):
        """
        Start a continuous listening loop.
        
        Args:
            callback: Function to call with each transcription
        """
        if not self._running:
            raise RuntimeError("RealtimeVoice not started")
            
        cb = callback or self._on_transcription
        if not cb:
            raise ValueError("No transcription callback provided")
            
        logger.info("Starting continuous listen loop...")
        
        def _loop():
            while self._running:
                try:
                    text = self._recorder.text()
                    if text and text.strip():
                        cb(text)
                except Exception as e:
                    logger.error(f"Listen loop error: {e}")
                    
        self._listen_thread = threading.Thread(target=_loop, daemon=True)
        self._listen_thread.start()
        
    def speak(self, text: str, blocking: bool = True):
        """
        Speak the given text.
        
        Args:
            text: Text to speak
            blocking: If True, wait for speech to complete
        """
        if not self._tts_stream:
            raise RuntimeError("RealtimeVoice not started")
            
        logger.debug(f"Speaking: {text[:50]}...")
        self._tts_stream.feed(text)
        
        if blocking:
            self._tts_stream.play()
        else:
            self._tts_stream.play_async()
            
    def speak_stream(self, token_generator: Generator[str, None, None], blocking: bool = True):
        """
        Stream tokens directly to TTS for minimum latency.
        
        Args:
            token_generator: Generator yielding text tokens
            blocking: If True, wait for speech to complete
        """
        if not self._tts_stream:
            raise RuntimeError("RealtimeVoice not started")
            
        logger.debug("Starting streaming TTS...")
        
        # Feed tokens as they arrive
        self._tts_stream.feed(token_generator)
        
        if blocking:
            self._tts_stream.play()
        else:
            self._tts_stream.play_async()
            
    def stop_speaking(self):
        """Stop current TTS playback immediately."""
        if self._tts_stream:
            self._tts_stream.stop()
            logger.debug("TTS playback stopped")
            
    def is_speaking(self) -> bool:
        """Check if TTS is currently playing."""
        if self._tts_stream:
            return self._tts_stream.is_playing()
        return False
        
    def stop(self):
        """Stop the voice pipeline and release resources."""
        logger.info("Stopping RealtimeVoice pipeline...")
        self._running = False
        
        if self._listen_thread and self._listen_thread.is_alive():
            self._listen_thread.join(timeout=2.0)
            
        if self._tts_stream:
            self._tts_stream.stop()
            
        if self._recorder:
            self._recorder.shutdown()
            
        if self._tts_engine:
            self._tts_engine.shutdown()
            
        logger.info("RealtimeVoice pipeline stopped")
        
    def __enter__(self):
        self.start()
        return self
        
    def __exit__(self, *args):
        self.stop()
