"""
VibeVoice TTS Engine for ARVIS
------------------------------
Wrapper for Microsoft's VibeVoice model for high-quality, real-time TTS.

Features:
- Real-time synthesis (RTF ~1.0x on GPU)
- Multiple English speakers with natural voices
- Long-form audio generation
- Streaming support

Requirements:
- VibeVoice cloned from: https://github.com/microsoft/VibeVoice
- pip install -e VibeVoice/
- CUDA GPU with ~4GB VRAM for 0.5B model
"""

import os
import sys
import logging
import threading
from typing import Iterator, Optional, Callable
from queue import Queue, Empty
from pathlib import Path

logger = logging.getLogger(__name__)

# Add VibeVoice to path if it exists
VIBEVOICE_DIR = Path(__file__).parent.parent.parent / "VibeVoice"

if VIBEVOICE_DIR.exists():
    if str(VIBEVOICE_DIR) not in sys.path:
        sys.path.insert(0, str(VIBEVOICE_DIR))

# Check if VibeVoice is available
VIBEVOICE_AVAILABLE = False
try:
    from vibevoice.modular.modeling_vibevoice_streaming_inference import VibeVoiceStreamingForConditionalGenerationInference
    from vibevoice.processor.vibevoice_streaming_processor import VibeVoiceStreamingProcessor
    VIBEVOICE_AVAILABLE = True
    logger.info("VibeVoice successfully imported")
except ImportError as e:
    logger.warning(f"VibeVoice not available: {e}")
    logger.warning("Install from: https://github.com/microsoft/VibeVoice")


# Helper for sentence splitting
class SentenceSplitter:
    def __init__(self):
        self.buffer = ""
        self.abbreviations = {"dr.", "mr.", "mrs.", "ms.", "prof.", "inc.", "ltd.", "co.", "etc.", "e.g.", "i.e."}

    def feed(self, text: str) -> Iterator[str]:
        """Feed text and yield complete sentences."""
        self.buffer += text
        
        while True:
            # Find closest sentence end
            min_idx = -1
            end_char = ""
            
            # Search for delimiters
            search_start = 0
            found_valid_delimiter = False
            
            while search_start < len(self.buffer):
                # Find first delimiter from search_start
                candidates = []
                for char in ['.', '?', '!', '\n']:
                    idx = self.buffer.find(char, search_start)
                    if idx != -1:
                        candidates.append((idx, char))
                
                if not candidates:
                    break
                
                # Pick earliest delimiter
                min_idx, end_char = min(candidates, key=lambda x: x[0])
                
                # Check for abbreviations (only for '.')
                if end_char == '.':
                    # Extract the word ending at this dot
                    # Look back for space or start of string
                    word_start = min_idx - 1
                    while word_start >= 0 and self.buffer[word_start] != ' ':
                        word_start -= 1
                    
                    last_word = self.buffer[word_start+1:min_idx+1].lower() # Include the dot
                    
                    if last_word in self.abbreviations:
                        # It is an abbreviation!
                        # If buffers ends right after this, we can't be sure if it's end of sentence or not
                        # e.g. "Is it Dr." (could be end) vs "Is it Dr. Smith"
                        if min_idx == len(self.buffer) - 1:
                            # End of buffer - wait for more text
                            return 
                        
                        # Not end of buffer - just ignore this dot as a delimiter
                        search_start = min_idx + 1
                        continue
                
                # If we get here, it's a valid delimiter
                found_valid_delimiter = True
                break
            
            if not found_valid_delimiter:
                break

            sentence = self.buffer[:min_idx+1].strip()
            self.buffer = self.buffer[min_idx+1:]
            
            if sentence:
                yield sentence
    
    def flush(self) -> Iterator[str]:
        """Flush remaining buffer."""
        if self.buffer.strip():
            yield self.buffer.strip()
        self.buffer = ""


class VibeVoiceEngine:
    """
    VibeVoice TTS engine wrapper compatible with ARVIS VoicePipeline.
    
    Features:
    - True streaming (Producer-Consumer)
    - Sentence-level synthesis
    """
    
    # Default model path
    DEFAULT_MODEL = "microsoft/VibeVoice-Realtime-0.5B"
    
    # Voice presets directory
    VOICES_DIR = VIBEVOICE_DIR / "demo" / "voices" / "streaming_model"
    
    # Available English speakers
    SPEAKERS = {
        "carter": "en-carter_man",
        "davis": "en-davis_man", 
        "emma": "en-emma_woman",
        "frank": "en-frank_man",
        "grace": "en-grace_woman",
        "mike": "en-mike_man",
    }
    
    def __init__(
        self,
        model_path: str = None,
        device: str = "cuda",
        speaker: str = "carter",
        sample_rate: int = 24000,
    ):
        if not VIBEVOICE_AVAILABLE:
            raise RuntimeError("VibeVoice is not available.")
        
        self.model_path = model_path or self.DEFAULT_MODEL
        self.device = device
        self.speaker = speaker.lower()
        self.sample_rate = sample_rate
        
        self._model = None
        self._processor = None
        self._voice_preset = None
        self._is_initialized = False
        self._lock = threading.Lock()
        
        # Callbacks
        self.on_audio_start: Optional[Callable] = None
        self.on_audio_stop: Optional[Callable] = None
        
        # Audio Player
        self._stop_event = threading.Event()
        
        logger.info(f"VibeVoiceEngine created (model={self.model_path}, device={device})")

    def _ensure_initialized(self):
        """Lazy initialization."""
        if self._is_initialized:
            return
        
        with self._lock:
            if self._is_initialized:
                return
            
            import torch
            logger.info(f"Loading VibeVoice model from: {self.model_path}...")
            
            try:
                self._processor = VibeVoiceStreamingProcessor.from_pretrained(self.model_path)
                
                # Setup model options based on device
                dtype = torch.bfloat16 if self.device == "cuda" else torch.float32
                attn = "flash_attention_2" if self.device == "cuda" else "sdpa"
                
                try:
                    self._model = VibeVoiceStreamingForConditionalGenerationInference.from_pretrained(
                        self.model_path,
                        torch_dtype=dtype,
                        device_map=self.device,
                        attn_implementation=attn
                    )
                except Exception:
                    # Fallback
                    self._model = VibeVoiceStreamingForConditionalGenerationInference.from_pretrained(
                        self.model_path,
                        torch_dtype=dtype,
                        device_map=self.device,  
                        attn_implementation="sdpa"
                    )
                
                self._model.eval()
                self._model.set_ddpm_inference_steps(num_steps=5)
                
                # Load voice
                voice_name = self.SPEAKERS.get(self.speaker, f"en-{self.speaker}_man")
                voice_file = self.VOICES_DIR / f"{voice_name}.pt"
                
                if not voice_file.exists():
                     # Fallback search
                     for f in self.VOICES_DIR.glob(f"*{self.speaker}*.pt"):
                         voice_file = f
                         break
                
                if voice_file.exists():
                    self._voice_preset = torch.load(voice_file, map_location=self.device, weights_only=False)
                else:
                    logger.warning(f"Voice {self.speaker} not found, using default.")
                    first = next(self.VOICES_DIR.glob("*.pt"), None)
                    if first:
                        self._voice_preset = torch.load(first, map_location=self.device, weights_only=False)

                self._is_initialized = True
                logger.info("✅ VibeVoice model loaded")
                
            except Exception as e:
                logger.error(f"Failed to load VibeVoice: {e}")
                raise

    def synthesize(self, text: str) -> bytes:
        """Synthesize single text block (Blocking)."""
        self._ensure_initialized()
        import io
        import torch
        import scipy.io.wavfile as wav
        import numpy as np
        
        import copy

        # Preprocessing
        inputs = self._processor.process_input_with_cached_prompt(
            text=text,
            cached_prompt=self._voice_preset,
            padding=True,
            return_tensors="pt",
            return_attention_mask=True,
        )
        for k, v in inputs.items():
            if torch.is_tensor(v):
                inputs[k] = v.to(self.device)
        
        # Generate with deepcopy of preset to strictly avoid side-effects
        # The tensor shape mismatch error (57 vs 54) proves the preset is mutating!
        outputs = self._model.generate(
            **inputs,
            max_new_tokens=None,
            cfg_scale=1.5,
            tokenizer=self._processor.tokenizer,
            generation_config={'do_sample': False},
            all_prefilled_outputs=copy.deepcopy(self._voice_preset) if self._voice_preset else None,
        )
        
        if outputs.speech_outputs and outputs.speech_outputs[0] is not None:
             audio = outputs.speech_outputs[0].cpu().float().numpy().squeeze()
             # Norm
             m = np.abs(audio).max()
             if m > 1.0: audio = audio / m
             
             # Int16
             audio_int16 = (audio * 32767).astype(np.int16)
             
             buf = io.BytesIO()
             wav.write(buf, self.sample_rate, audio_int16)
             return buf.getvalue()
        return b""

    def _play_worker(self, audio_queue: Queue):
        """Worker to play audio chunks from queue."""
        import sounddevice as sd
        import numpy as np
        import scipy.io.wavfile as wav
        import io
        
        try:
            stream = sd.OutputStream(samplerate=self.sample_rate, channels=1, dtype='int16')
            stream.start()
            
            if self.on_audio_start:
                self.on_audio_start()
            
            while not self._stop_event.is_set():
                try:
                    # Wait for audio, timeout to check stop flag
                    chunk_bytes = audio_queue.get(timeout=0.1)
                    if chunk_bytes is None: # Sentinel
                        break
                        
                    # Parse WAV bytes back to array (inefficient but safe for now)
                    # Ideally synthesize returns raw numpy array to avoid encode/decode
                    try:
                        _, data = wav.read(io.BytesIO(chunk_bytes))
                        stream.write(data)
                    except Exception as e:
                        logger.error(f"Playback error: {e}")
                        
                except Empty:
                    continue
            
            stream.stop()
            stream.close()
            
        except Exception as e:
            logger.error(f"Audio stream error: {e}")
        finally:
            if self.on_audio_stop:
                self.on_audio_stop()

    def stream_synthesis(self, text_iterator: Iterator[str]):
        """
        Consumes text iterator, synthesizes sentences on the fly, and plays them.
        This is the main streaming entry point.
        """
        self._ensure_initialized()
        self._stop_event.clear()
        
        import io
        import torch
        import copy
        import numpy as np
        import sounddevice as sd
        
        # Audio Queue for playback thread
        audio_queue = Queue()
        playback_thread = threading.Thread(target=self._play_worker, args=(audio_queue,))
        playback_thread.start()
        
        splitter = SentenceSplitter()
        
        try:
            for text_chunk in text_iterator:
                if self._stop_event.is_set():
                    break
                
                # Split chunk into sentences
                for sentence in splitter.feed(text_chunk):
                     if not sentence.strip():
                         continue
                     
                     # Check stop again
                     if self._stop_event.is_set():
                         break
                     
                     logger.debug(f"Synthesizing: {sentence}")
                     # Generate Audio (Blocking inference)
                     audio_bytes = self.synthesize(sentence)
                     
                     # Push to player
                     if audio_bytes:
                         audio_queue.put(audio_bytes)
            
            # Flush remaining text
            for sentence in splitter.flush():
                if sentence.strip() and not self._stop_event.is_set():
                     audio_bytes = self.synthesize(sentence)
                     if audio_bytes:
                         audio_queue.put(audio_bytes)
                         
        except Exception as e:
            logger.error(f"Streaming synthesis error: {e}")
        finally:
            # Signal playback to stop when done
            audio_queue.put(None)
            playback_thread.join()

    def stop(self):
        self._stop_event.set()
        import sounddevice as sd
        try:
            sd.stop()
        except:
            pass

    def shutdown(self):
        self.stop()
        self._model = None
        self._processor = None
        self._is_initialized = False


class VibeVoiceTTSStream:
    """
    Acts as a bridge between RealtimeTTS interface and VibeVoiceEngine.
    """
    def __init__(self, engine: VibeVoiceEngine, on_audio_stream_start=None, on_audio_stream_stop=None):
        self.engine = engine
        self.engine.on_audio_start = on_audio_stream_start
        self.engine.on_audio_stop = on_audio_stream_stop
        self._generator_queue = Queue()
        self._input_mode = "text" # or "generator"
        self._text_buffer = []

    def feed(self, text_or_gen):
        """
        Accepts str or iterator.
        If iterator, we assume it's the stream source.
        """
        if hasattr(text_or_gen, '__iter__') and not isinstance(text_or_gen, str):
            self._input_mode = "generator"
            self._generator_queue.put(text_or_gen)
        else:
            self._input_mode = "text"
            if text_or_gen:
                self._text_buffer.append(text_or_gen)

    def play_async(self):
        """
        Start streaming playback in background. 
        """
        def _stream_worker():
            if self._input_mode == "generator":
                # Consumer generator from queue (assume single stream for now)
                try:
                    gen = self._generator_queue.get_nowait()
                    self.engine.stream_synthesis(gen)
                except Empty:
                    pass
            else:
                # Text buffer mode - construct generator
                def _buf_gen():
                    full_text = "".join(self._text_buffer)
                    self._text_buffer = []
                    yield full_text
                
                self.engine.stream_synthesis(_buf_gen())

        threading.Thread(target=_stream_worker, daemon=True).start()

    def play(self, muted=False):
        """Synchronous play (blocking)."""
        if self._input_mode == "text":
            full = "".join(self._text_buffer)
            self._text_buffer = []
            if full.strip():
                if muted:
                    # Just warm up
                    self.engine.synthesize("Warm up.")
                else:
                    audio = self.engine.synthesize(full)
                    # Poor man's play
                    import sounddevice as sd
                    import scipy.io.wavfile as wav
                    import io
                    # ... decode and play ... (omitted for brevity as we focus on async)
                    # For VibeVoice proper sync play, we can reuse stream logic
                    self.engine.stream_synthesis(iter([full]))
    
    def stop(self):
        self.engine.stop()
