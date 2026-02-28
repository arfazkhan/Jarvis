"""
Audio Recorder
-------------
Handles microphone recording using sounddevice with VAD (Voice Activity Detection).
"""

import os
import time
import numpy as np
import sounddevice as sd
from scipy.io.wavfile import write
import queue
import io

class AudioRecorder:
    def __init__(self, sample_rate=16000):
        """Initialize recorder with sample rate"""
        self.fs = sample_rate
        # VAD Parameters
        self.threshold = 0.01  # Default, will calibrate
        self.silence_limit = 1.2  # Reduced to 1.2s (was 1.5s) for snappier response
        self.min_speech_duration = 0.3  # Reduced to 0.3s (was 0.5s) to catch short replies
        self.chunk_duration = 0.08  # 80ms (1280 samples) - Native for openwakeword
        self.chunk_size = int(self.fs * self.chunk_duration)
    
    def calibrate_noise(self, duration=1.0):
        """Measure background noise to set threshold"""
        print(f"🤫 Calibrating background noise ({duration}s)...")
        recording = sd.rec(int(duration * self.fs), samplerate=self.fs, channels=1)
        sd.wait()
        
        # Calculate RMS energy
        rms = np.sqrt(np.mean(recording**2))
        # Set threshold slightly above noise floor (e.g., +10dB or 3x amplitude)
        # Tuned: 2.5x noise floor + lower base floor for better sensitivity
        self.threshold = max(rms * 2.5, 0.003) 
        print(f"✅ Auto-calibrated threshold: {self.threshold:.4f}")
        
    def record(self, duration=5, output_file="command.wav") -> str:
        """Fixed duration recording (legacy)"""
        try:
            print(f"🎤 Recording for {duration} seconds... (Speak now)")
            myrecording = sd.rec(int(duration * self.fs), samplerate=self.fs, channels=1)
            for i in range(duration):
                time.sleep(1)
                print("." * (i+1), end="\r")
            sd.wait()
            print("\n✅ Recording complete")
            write(output_file, self.fs, myrecording)
            return output_file
        except Exception as e:
            print(f"❌ Recording failed: {e}")
            return None

    def record_auto(self, output_file="command.wav", max_duration=15) -> str:
        """
        Smart recording with VAD:
        1. Waits for speech
        2. Records while speaking
        3. Stops after silence
        """
        q = queue.Queue()
        
        def callback(indata, frames, time, status):
            if status:
                print(status)
            q.put(indata.copy())
            
        # Calibrate if needed
        if self.threshold == 0.01:
            self.calibrate_noise()
            
        print("🎤 Listening... (Speak now)")
        
        audio_data = []
        speech_started = False
        silence_start_time = None
        start_time = time.time()
        
        # Buffer to keep pre-speech audio (0.5s)
        pre_buffer_size = int(0.5 / self.chunk_duration)
        pre_buffer = [] 
        
        try:
            with sd.InputStream(samplerate=self.fs, channels=1, callback=callback):
                while True:
                    # Timeout check
                    if time.time() - start_time > max_duration:
                        print("\n⏱️ Timeout reached")
                        break
                        
                    # Get chunk
                    chunk = q.get()
                    rms = np.sqrt(np.mean(chunk**2))
                    
                    is_speech = rms > self.threshold
                    
                    if not speech_started:
                        if is_speech:
                            print("\n🗣️ Speech detected! Recording...")
                            speech_started = True
                            # Add pre-buffer
                            audio_data.extend(pre_buffer)
                            audio_data.append(chunk)
                        else:
                            # Maintain circular pre-buffer
                            pre_buffer.append(chunk)
                            if len(pre_buffer) > pre_buffer_size:
                                pre_buffer.pop(0)
                            # Dot animation while waiting
                            if int(time.time() * 10) % 5 == 0:
                                print(".", end="", flush=True)
                    else:
                        # Recording speech or silence
                        audio_data.append(chunk)
                        
                        if is_speech:
                            silence_start_time = None # Reset silence timer
                        else:
                            if silence_start_time is None:
                                silence_start_time = time.time()
                            elif time.time() - silence_start_time > self.silence_limit:
                                print(f"\n🤫 Silence detected ({self.silence_limit}s). Stopping.")
                                break
                                
            # Check if we actually recorded anything significant
            total_samples = sum(len(c) for c in audio_data)
            duration = total_samples / self.fs
            
            if duration < self.min_speech_duration:
                print("\n⚠️ Recording too short, ignoring.")
                return None
            
            # Save file
            full_audio = np.concatenate(audio_data, axis=0)
            write(output_file, self.fs, full_audio)
            return output_file
            
        except Exception as e:
            print(f"\n❌ Smart recording failed: {e}")
            return None

    def stream(self):
        """
        Yield audio chunks for wake word detection.
        Yields: np.ndarray (Int16)
        """
        q = queue.Queue()
        
        def callback(indata, frames, time, status):
            if status:
                print(status)
            q.put(indata.copy())
            
        try:
            with sd.InputStream(samplerate=self.fs, channels=1, callback=callback):
                while True:
                    chunk = q.get()
                    # Convert float32 to int16 for openwakeword and FLATTEN to 1D array
                    # sounddevice returns (samples, channels) e.g. (1280, 1) -> we need (1280,)
                    chunk_int16 = (chunk * 32767).astype(np.int16).flatten()
                    yield chunk_int16
                    
        except Exception as e:
            print(f"Stream error: {e}")
    
    def record_semantic(self, semantic_vad, transcriber, output_file="command.wav", max_duration=20) -> str:
        """
        Semantic-aware recording:
        1. Detects speech with SileroVAD
        2. On silence, checks sentence completeness with LLM
        3. If incomplete, extends recording
        4. If complete, finalizes
        """
        q = queue.Queue()
        
        def callback(indata, frames, time, status):
            if status:
                print(status)
            q.put(indata.copy())
        
        print("🎤 Listening... (Speak now)")
        
        audio_data = []
        speech_started = False
        silence_start_time = None
        start_time = time.time()
        
        # Buffer for pre-speech (0.5s)
        pre_buffer_size = int(0.5 / self.chunk_duration)
        pre_buffer = []
        
        try:
            with sd.InputStream(samplerate=self.fs, channels=1, callback=callback):
                while True:
                    # Timeout check
                    if time.time() - start_time > max_duration:
                        print("\n⏱️ Timeout reached")
                        break
                    
                    # Get chunk
                    chunk = q.get()
                    
                    # Use SileroVAD for speech detection (with fallback)
                    try:
                        speech_prob = semantic_vad.detect_speech(chunk.flatten(), self.fs)
                        # Also use energy as fallback
                        rms = np.sqrt(np.mean(chunk**2))
                        # Hybrid: Either SileroVAD OR energy
                        is_speech = (speech_prob > 0.3) or (rms > self.threshold)
                    except Exception as e:
                        # Fallback to pure energy
                        rms = np.sqrt(np.mean(chunk**2))
                        is_speech = rms > self.threshold
                    
                    if not speech_started:
                        if is_speech:
                            print("\n🗣️ Speech detected! Recording...")
                            speech_started = True
                            # Add pre-buffer
                            audio_data.extend(pre_buffer)
                            audio_data.append(chunk)
                        else:
                            # Maintain circular pre-buffer
                            pre_buffer.append(chunk)
                            if len(pre_buffer) > pre_buffer_size:
                                pre_buffer.pop(0)
                    else:
                        # Recording speech or silence
                        audio_data.append(chunk)
                        
                        if is_speech:
                            silence_start_time = None  # Reset
                        else:
                            # Silence detected - check if sentence is complete
                            if silence_start_time is None:
                                silence_start_time = time.time()
                            
                            silence_duration = time.time() - silence_start_time
                            
                            # After 0.8s of silence, check completeness
                            if silence_duration > 0.8:
                                print("\n🤔 Checking sentence completeness...")
                                
                                # Quick transcription of what we have so far
                                temp_audio = np.concatenate(audio_data, axis=0)
                                temp_file = "_semantic_check.wav"
                                write(temp_file, self.fs, temp_audio)
                                
                                partial_text = transcriber.transcribe(temp_file)
                                os.remove(temp_file)
                                
                                # Check if complete
                                if not partial_text.startswith("Error"):
                                    is_complete = semantic_vad.is_sentence_complete(partial_text)
                                    
                                    if is_complete:
                                        print(f"✅ Sentence complete: '{partial_text[:50]}...'")
                                        break
                                    else:
                                        print(f"⏳ Incomplete, waiting: '{partial_text[:30]}...'")
                                        # Reset silence timer to wait longer
                                        silence_start_time = time.time()
                                        # But also check if we've waited TOO long
                                        if silence_duration > 3.0:
                                            print("⏱️ Max wait reached, finalizing...")
                                            break
            
            # Check if we have enough audio
            if not audio_data:
                return None
            
            total_samples = sum(len(c) for c in audio_data)
            duration = total_samples / self.fs
            
            if duration < self.min_speech_duration:
                print("\n⚠️ Recording too short, ignoring.")
                return None
            
            # Save
            full_audio = np.concatenate(audio_data, axis=0)
            write(output_file, self.fs, full_audio)
            return output_file
            
        except Exception as e:
            print(f"\n❌ Semantic recording failed: {e}")
            return None
