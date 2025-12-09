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

class AudioRecorder:
    def __init__(self, sample_rate=16000):
        """Initialize recorder with sample rate"""
        self.fs = sample_rate
        # VAD Parameters
        self.threshold = 0.01  # Default, will calibrate
        self.silence_limit = 1.2  # Reduced to 1.2s (was 1.5s) for snappier response
        self.min_speech_duration = 0.3  # Reduced to 0.3s (was 0.5s) to catch short replies
        self.chunk_duration = 0.05  # Reduced to 50ms (was 100ms) for finer resolution
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
