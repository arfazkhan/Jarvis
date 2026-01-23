"""
Edge TTS Engine for ARVIS
-------------------------
Wrapper for Microsoft Edge TTS (cloud-based, free, no API key needed).

Features:
- 400+ voices in 75+ languages
- Low latency (~200-500ms)
- No GPU required
- Free to use

Requirements:
- pip install edge-tts
- Internet connection
"""

import os
import sys
import logging
import asyncio
import tempfile
import threading
from typing import Optional, Callable
from queue import Queue, Empty
from pathlib import Path

logger = logging.getLogger(__name__)

# Check if edge-tts is available
EDGETTS_AVAILABLE = False
try:
    import edge_tts
    EDGETTS_AVAILABLE = True
    logger.info("Edge TTS successfully imported")
except ImportError as e:
    logger.warning(f"Edge TTS not available: {e}")
    logger.warning("Install with: pip install edge-tts")


# Popular English voices
EDGE_VOICES = {
    # US English
    "guy": "en-US-GuyNeural",  # Male, conversational
    "jenny": "en-US-JennyNeural",  # Female, conversational
    "aria": "en-US-AriaNeural",  # Female, professional
    "davis": "en-US-DavisNeural",  # Male, friendly
    "jane": "en-US-JaneNeural",  # Female, professional
    "jason": "en-US-JasonNeural",  # Male, neutral
    "sara": "en-US-SaraNeural",  # Female, friendly
    "tony": "en-US-TonyNeural",  # Male, casual
    
    # UK English
    "ryan": "en-GB-RyanNeural",  # Male, professional
    "sonia": "en-GB-SoniaNeural",  # Female, professional
    "libby": "en-GB-LibbyNeural",  # Female, casual
    
    # Indian English
    "neerja": "en-IN-NeerjaNeural",  # Female
    "prabhat": "en-IN-PrabhatNeural",  # Male
    
    # Australian English
    "natasha": "en-AU-NatashaNeural",  # Female
    "william": "en-AU-WilliamNeural",  # Male
}


class EdgeTTSEngine:
    """
    Edge TTS engine wrapper compatible with ARVIS VoicePipeline.
    
    Provides similar interface to RealtimeTTS engines for easy integration.
    """
    
    def __init__(
        self,
        voice: str = "guy",
        rate: str = "+0%",
        pitch: str = "+0Hz",
        volume: str = "+0%",
        sample_rate: int = 24000,
    ):
        """
        Initialize Edge TTS engine.
        
        Args:
            voice: Voice name (guy, jenny, aria, davis, ryan, neerja, etc.)
            rate: Speech rate adjustment (e.g., "+10%", "-20%")
            pitch: Pitch adjustment (e.g., "+5Hz", "-10Hz")
            volume: Volume adjustment (e.g., "+10%", "-5%")
            sample_rate: Audio sample rate (24000 for Edge TTS)
        """
        if not EDGETTS_AVAILABLE:
            raise RuntimeError(
                "Edge TTS is not available. Install with:\n"
                "  pip install edge-tts"
            )
        
        # Get full voice name
        self.voice = EDGE_VOICES.get(voice.lower(), voice)
        self.rate = rate
        self.pitch = pitch
        self.volume = volume
        self.sample_rate = sample_rate
        
        # Audio playback
        self._audio_queue = Queue()
        self._is_playing = False
        self._playback_thread = None
        
        # Callbacks (compatible with RealtimeTTS)
        self.on_audio_start: Optional[Callable] = None
        self.on_audio_stop: Optional[Callable] = None
        
        # Event loop for async operations
        self._loop = None
        
        logger.info(f"EdgeTTSEngine created (voice={self.voice})")
    
    def _get_loop(self):
        """Get or create event loop."""
        if self._loop is None or self._loop.is_closed():
            try:
                self._loop = asyncio.get_event_loop()
            except RuntimeError:
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
        return self._loop
    
    async def _synthesize_async(self, text: str) -> bytes:
        """Synthesize text to audio bytes asynchronously."""
        communicate = edge_tts.Communicate(
            text,
            self.voice,
            rate=self.rate,
            pitch=self.pitch,
            volume=self.volume,
        )
        
        # Collect audio data
        audio_data = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data += chunk["data"]
        
        return audio_data
    
    def synthesize(self, text: str) -> bytes:
        """
        Synthesize text to audio bytes.
        
        Args:
            text: Text to synthesize
            
        Returns:
            Audio bytes (MP3 format)
        """
        try:
            loop = self._get_loop()
            return loop.run_until_complete(self._synthesize_async(text))
        except Exception as e:
            logger.error(f"Edge TTS synthesis error: {e}")
            raise
    
    def feed(self, text: str):
        """
        Feed text for synthesis (compatible with RealtimeTTS interface).
        Queues text for playback.
        """
        if text and text.strip():
            self._audio_queue.put(text)
    
    def play(self, muted: bool = False):
        """
        Play all queued text synchronously.
        
        Args:
            muted: If True, synthesize but don't play (for prewarming)
        """
        texts = []
        while not self._audio_queue.empty():
            try:
                texts.append(self._audio_queue.get_nowait())
            except Empty:
                break
        
        if not texts:
            return
        
        full_text = " ".join(texts)
        
        if self.on_audio_start:
            self.on_audio_start()
        
        self._is_playing = True
        try:
            if not muted:
                self._play_audio(full_text)
        finally:
            self._is_playing = False
            if self.on_audio_stop:
                self.on_audio_stop()
    
    def play_async(self):
        """Play queued text asynchronously in background thread."""
        self._playback_thread = threading.Thread(target=self.play, daemon=True)
        self._playback_thread.start()
    
    def _play_audio(self, text: str):
        """Internal method to synthesize and play audio."""
        try:
            import sounddevice as sd
            import numpy as np
            import io
            
            # Use pydub to decode MP3 if available, otherwise use soundfile
            try:
                from pydub import AudioSegment
                
                # Synthesize to MP3
                audio_bytes = self.synthesize(text)
                
                # Decode MP3 using pydub
                audio_segment = AudioSegment.from_mp3(io.BytesIO(audio_bytes))
                
                # Convert to numpy array
                samples = np.array(audio_segment.get_array_of_samples())
                if audio_segment.channels == 2:
                    samples = samples.reshape((-1, 2))
                    samples = samples.mean(axis=1)  # Convert to mono
                
                # Normalize
                samples = samples.astype(np.float32) / 32768.0
                
                # Play
                if self._is_playing:
                    sd.play(samples, audio_segment.frame_rate)
                    sd.wait()
                    
            except ImportError:
                # Fallback: save to temp file and use pygame/another player
                logger.warning("pydub not available, using temp file method")
                
                audio_bytes = self.synthesize(text)
                
                # Save to temp file
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                    f.write(audio_bytes)
                    temp_path = f.name
                
                # Try to play with pygame
                try:
                    import pygame
                    pygame.mixer.init()
                    pygame.mixer.music.load(temp_path)
                    pygame.mixer.music.play()
                    while pygame.mixer.music.get_busy():
                        pygame.time.Clock().tick(10)
                except ImportError:
                    logger.warning("pygame not available, install pydub for audio playback")
                finally:
                    # Clean up temp file
                    try:
                        os.unlink(temp_path)
                    except:
                        pass
                    
        except Exception as e:
            logger.error(f"Audio playback error: {e}")
    
    def stop(self):
        """Stop current playback."""
        self._is_playing = False
        try:
            import sounddevice as sd
            sd.stop()
        except:
            pass
        
        # Clear queue
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except Empty:
                break
    
    def shutdown(self):
        """Shutdown the engine and release resources."""
        self.stop()
        logger.info("Edge TTS engine shutdown")


class EdgeTTSTTSStream:
    """
    Wrapper to make Edge TTS work with RealtimeTTS's TextToAudioStream interface.
    
    This provides a drop-in replacement for RealtimeTTS's stream class.
    """
    
    def __init__(
        self,
        engine: EdgeTTSEngine,
        on_audio_stream_start: Optional[Callable] = None,
        on_audio_stream_stop: Optional[Callable] = None,
    ):
        self.engine = engine
        self.engine.on_audio_start = on_audio_stream_start
        self.engine.on_audio_stop = on_audio_stream_stop
        self._text_buffer = []
    
    def feed(self, text):
        """Feed text or generator to the stream."""
        if hasattr(text, '__iter__') and not isinstance(text, str):
            # It's a generator
            for chunk in text:
                if chunk:
                    self._text_buffer.append(chunk)
        else:
            if text:
                self._text_buffer.append(text)
    
    def play(self, muted: bool = False):
        """Play all fed text synchronously."""
        full_text = "".join(self._text_buffer)
        self._text_buffer = []
        
        if full_text.strip():
            self.engine.feed(full_text)
            self.engine.play(muted=muted)
    
    def play_async(self):
        """Play asynchronously."""
        full_text = "".join(self._text_buffer)
        self._text_buffer = []
        
        if full_text.strip():
            self.engine.feed(full_text)
            self.engine.play_async()
    
    def stop(self):
        """Stop playback."""
        self.engine.stop()
        self._text_buffer = []
