"""
Speaker (TTS)
-----------
Text-to-Speech using Kokoro-82M model.
"""

import numpy as np
import sounddevice as sd
import warnings

class Speaker:
    def __init__(self, voice="af_bella"):  # American Male "Adam" voice
        """Initialize Kokoro TTS"""
        print("🔊 Loading Kokoro TTS...")
        try:
            # Suppress typing warnings for Python 3.12+ compatibility
            warnings.filterwarnings('ignore', category=DeprecationWarning)
            
            from kokoro import KPipeline
            self.pipeline = KPipeline(lang_code='a')  # 'a' for American English
            self.voice = voice
            print("✅ Kokoro TTS loaded")
        except Exception as e:
            print(f"⚠️ Kokoro TTS unavailable: {e}")
            print("   Continuing without voice output (text-only mode)")
            self.pipeline = None
    
    def speak(self, text: str, voice=None) -> bool:
        """
        Generate and play speech from text.
        
        Args:
            text: Text to speak
            voice: Voice to use (defaults to self.voice)
            
        Returns:
            bool: True if successful
        """
        if not self.pipeline:
            print(f"[TTS Disabled]: {text}")
            return False
            
        if not text or not text.strip():
            return False
            
        try:
            # Generate audio using KPipeline - returns generator of (graphemes, phonemes, audio)
            all_audio = []
            for graphemes, phonemes, audio in self.pipeline(
                text, 
                voice=voice or self.voice,
                speed=1.0
            ):
                if audio is not None:
                    all_audio.append(audio)
            
            if all_audio:
                # Concatenate all audio chunks
                audio_samples = np.concatenate(all_audio)
                
                # Play audio (Kokoro uses 24kHz)
                sd.play(audio_samples, samplerate=24000)
                sd.wait()  # Wait until audio finishes
            
            return True
            
        except Exception as e:
            print(f"❌ TTS failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def stop(self):
        """Stop current playback"""
        sd.stop()
