"""
CosyVoice TTS Engine for ARVIS
------------------------------
Wrapper for Alibaba's CosyVoice model for high-quality, low-latency TTS.

Features:
- ~150ms first-audio latency
- Bi-streaming (text-in, audio-out)
- 9 languages supported
- Emotion/speed/volume control via instructions

Requirements:
- CosyVoice cloned from: https://github.com/FunAudioLLM/CosyVoice
- pip install -r CosyVoice/requirements.txt
- CUDA GPU with ~2-3GB VRAM for 0.5B model
"""

import os
import sys
import logging
import threading
from typing import Iterator, Optional, Callable
from queue import Queue, Empty
from pathlib import Path

logger = logging.getLogger(__name__)

# Configure torchaudio to use soundfile backend instead of torchcodec
# This avoids the FFmpeg dependency on Windows
try:
    import torchaudio
    import torch
    import numpy as np
    
    # Save original load function
    _original_torchaudio_load = torchaudio.load
    
    def _patched_torchaudio_load(filepath, *args, **kwargs):
        """
        Patched torchaudio.load that falls back to scipy when torchcodec fails.
        This avoids the FFmpeg dependency on Windows.
        """
        try:
            return _original_torchaudio_load(filepath, *args, **kwargs)
        except Exception as e:
            if "torchcodec" in str(e).lower() or "libtorchcodec" in str(e).lower() or "ffmpeg" in str(e).lower():
                # Fallback to scipy for reading audio
                try:
                    import soundfile as sf
                    audio_data, sample_rate = sf.read(str(filepath), dtype='float32')
                    
                    # Convert to torch tensor (channels, samples)
                    if len(audio_data.shape) == 1:
                        # Mono: add channel dimension
                        waveform = torch.from_numpy(audio_data).unsqueeze(0)
                    else:
                        # Stereo: transpose to (channels, samples)
                        waveform = torch.from_numpy(audio_data.T)
                    
                    logger.info(f"Loaded audio via soundfile fallback: {filepath}")
                    return waveform, sample_rate
                except Exception as sf_error:
                    logger.error(f"Soundfile fallback also failed: {sf_error}")
                    raise
            else:
                raise
    
    # Apply monkey-patch
    torchaudio.load = _patched_torchaudio_load
    logger.info("Patched torchaudio.load with soundfile fallback")
    
except Exception as e:
    logger.warning(f"Could not patch torchaudio: {e}")

# Add CosyVoice to path if it exists
COSYVOICE_DIR = Path(__file__).parent.parent.parent / "CosyVoice"
MATCHA_TTS_DIR = COSYVOICE_DIR / "third_party" / "Matcha-TTS"

if COSYVOICE_DIR.exists():
    if str(COSYVOICE_DIR) not in sys.path:
        sys.path.insert(0, str(COSYVOICE_DIR))
    if MATCHA_TTS_DIR.exists() and str(MATCHA_TTS_DIR) not in sys.path:
        sys.path.insert(0, str(MATCHA_TTS_DIR))

# Check if CosyVoice is available
COSYVOICE_AVAILABLE = False
try:
    from cosyvoice.cli.cosyvoice import AutoModel
    COSYVOICE_AVAILABLE = True
    logger.info("CosyVoice successfully imported")
except ImportError as e:
    logger.warning(f"CosyVoice not available: {e}")
    logger.warning("Install from: https://github.com/FunAudioLLM/CosyVoice")


class CosyVoiceEngine:
    """
    CosyVoice TTS engine wrapper compatible with ARVIS VoicePipeline.
    
    Provides similar interface to RealtimeTTS engines for easy integration.
    """
    
    # Model directory relative to CosyVoice folder
    MODEL_DIR = COSYVOICE_DIR / "pretrained_models"
    
    # Default reference audio for voice cloning/cross-lingual
    DEFAULT_PROMPT_AUDIO = COSYVOICE_DIR / "asset" / "zero_shot_prompt.wav"
    
    def __init__(
        self,
        model_name: str = "Fun-CosyVoice3-0.5B",
        device: str = "cuda",
        speaker: str = None,  # Not used directly - uses reference audio
        sample_rate: int = 22050,
    ):
        """
        Initialize CosyVoice engine.
        
        Args:
            model_name: Model to use (Fun-CosyVoice3-0.5B recommended)
            device: Device to run on ("cuda" or "cpu")
            speaker: Not used for CosyVoice3 (uses reference audio)
            sample_rate: Audio sample rate (set by model)
        """
        if not COSYVOICE_AVAILABLE:
            raise RuntimeError(
                "CosyVoice is not available. Please install from:\n"
                "  git clone https://github.com/FunAudioLLM/CosyVoice.git\n"
                "  cd CosyVoice && pip install -r requirements.txt"
            )
        
        self.model_name = model_name
        self.device = device
        self.sample_rate = sample_rate
        self._model = None
        self._is_initialized = False
        self._lock = threading.Lock()
        
        # Audio playback
        self._audio_queue = Queue()
        self._is_playing = False
        self._playback_thread = None
        
        # Callbacks (compatible with RealtimeTTS)
        self.on_audio_start: Optional[Callable] = None
        self.on_audio_stop: Optional[Callable] = None
        
        logger.info(f"CosyVoiceEngine created (model={model_name}, device={device})")
    
    def _ensure_initialized(self):
        """Lazy initialization to avoid loading model until needed."""
        if self._is_initialized:
            return
        
        with self._lock:
            if self._is_initialized:
                return
            
            model_path = self.MODEL_DIR / self.model_name
            
            # Check if model exists, if not download it
            if not model_path.exists():
                logger.info(f"Model not found at {model_path}, downloading...")
                self._download_model()
            
            logger.info(f"Loading CosyVoice model from: {model_path}...")
            try:
                self._model = AutoModel(model_dir=str(model_path))
                self.sample_rate = self._model.sample_rate
                self._is_initialized = True
                logger.info(f"✅ CosyVoice model loaded (sample_rate={self.sample_rate})")
            except Exception as e:
                logger.error(f"Failed to load CosyVoice model: {e}")
                raise
    
    def _download_model(self):
        """Download the model from HuggingFace."""
        try:
            from huggingface_hub import snapshot_download
            
            # Model mapping
            hf_models = {
                "Fun-CosyVoice3-0.5B": "FunAudioLLM/Fun-CosyVoice3-0.5B-2512",
                "CosyVoice2-0.5B": "FunAudioLLM/CosyVoice2-0.5B",
                "CosyVoice-300M": "FunAudioLLM/CosyVoice-300M",
                "CosyVoice-300M-SFT": "FunAudioLLM/CosyVoice-300M-SFT",
            }
            
            hf_model = hf_models.get(self.model_name)
            if not hf_model:
                raise ValueError(f"Unknown model: {self.model_name}")
            
            logger.info(f"Downloading {hf_model}...")
            self.MODEL_DIR.mkdir(parents=True, exist_ok=True)
            local_dir = self.MODEL_DIR / self.model_name
            snapshot_download(hf_model, local_dir=str(local_dir))
            logger.info(f"✅ Model downloaded to {local_dir}")
            
        except Exception as e:
            logger.error(f"Failed to download model: {e}")
            raise
    
    def synthesize(self, text: str) -> bytes:
        """
        Synthesize text to audio bytes.
        
        Args:
            text: Text to synthesize
            
        Returns:
            Audio bytes (WAV format)
        """
        self._ensure_initialized()
        
        try:
            import io
            import torchaudio
            
            # Use cross-lingual mode with English prompt
            prompt_audio = str(self.DEFAULT_PROMPT_AUDIO)
            prompt_text = "You are a helpful assistant.<|endofprompt|>"
            
            # Generate audio
            for chunk in self._model.inference_cross_lingual(
                f"{prompt_text}{text}",
                prompt_audio,
                stream=False
            ):
                if 'tts_speech' in chunk:
                    audio_tensor = chunk['tts_speech']
                    
                    # Convert to bytes
                    buffer = io.BytesIO()
                    torchaudio.save(buffer, audio_tensor, self.sample_rate, format="wav")
                    return buffer.getvalue()
            
            return b''
            
        except Exception as e:
            logger.error(f"CosyVoice synthesis error: {e}")
            raise
    
    def stream_synthesize(self, text: str) -> Iterator[bytes]:
        """
        Stream synthesize text to audio chunks.
        
        Args:
            text: Text to synthesize
            
        Yields:
            Audio chunks (bytes)
        """
        self._ensure_initialized()
        
        try:
            import io
            import torchaudio
            
            prompt_audio = str(self.DEFAULT_PROMPT_AUDIO)
            prompt_text = "You are a helpful assistant.<|endofprompt|>"
            
            # Stream generate audio
            for chunk in self._model.inference_cross_lingual(
                f"{prompt_text}{text}",
                prompt_audio,
                stream=True
            ):
                if 'tts_speech' in chunk and chunk['tts_speech'] is not None:
                    audio_tensor = chunk['tts_speech']
                    
                    buffer = io.BytesIO()
                    torchaudio.save(buffer, audio_tensor, self.sample_rate, format="wav")
                    yield buffer.getvalue()
                    
        except Exception as e:
            logger.error(f"CosyVoice streaming error: {e}")
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
        self._ensure_initialized()
        
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
            
            prompt_audio = str(self.DEFAULT_PROMPT_AUDIO)
            
            # Collect all audio chunks first, then play (more reliable than streaming)
            audio_chunks = []
            
            # Use inference_cross_lingual with <|en|> prefix for English
            # Format: <|en|>English text here
            english_text = f"<|en|>{text}"
            
            for chunk in self._model.inference_cross_lingual(
                english_text,
                prompt_audio,
                stream=False  # Non-streaming for better quality
            ):
                if not self._is_playing:
                    break
                    
                if 'tts_speech' in chunk and chunk['tts_speech'] is not None:
                    audio_tensor = chunk['tts_speech']
                    
                    # Convert tensor to numpy - handle both CPU and GPU tensors
                    if hasattr(audio_tensor, 'cpu'):
                        audio_data = audio_tensor.cpu().numpy().squeeze()
                    else:
                        audio_data = audio_tensor.numpy().squeeze()
                    
                    audio_chunks.append(audio_data)
            
            # Concatenate all chunks and play once
            if audio_chunks:
                full_audio = np.concatenate(audio_chunks)
                
                # Normalize to float32
                if full_audio.dtype != np.float32:
                    full_audio = full_audio.astype(np.float32)
                
                # Ensure correct range [-1, 1]
                max_val = np.abs(full_audio).max()
                if max_val > 1.0:
                    full_audio = full_audio / max_val
                
                # Play the complete audio
                sd.play(full_audio, self.sample_rate)
                sd.wait()
                    
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
        
        if self._model is not None:
            del self._model
            self._model = None
            self._is_initialized = False
            
            # Clear CUDA cache
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except:
                pass
        
        logger.info("CosyVoice engine shutdown")


class CosyVoiceTTSStream:
    """
    Wrapper to make CosyVoice work with RealtimeTTS's TextToAudioStream interface.
    
    This provides a drop-in replacement for RealtimeTTS's stream class.
    """
    
    def __init__(
        self,
        engine: CosyVoiceEngine,
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
