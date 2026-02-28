"""
Wake Word Engine
---------------
Handles offline wake word detection using openwakeword.
Cross-platform (Windows/Linux/Mac).
"""

import os
import numpy as np
import openwakeword
from openwakeword.model import Model

class WakeWordEngine:
    def __init__(self, model_names=["hey_jarvis_v0.1"], threshold=0.5):
        """
        Initialize the wake word engine.
        
        Args:
            model_names: List of model names to load (default: hey_jarvis)
            threshold: Confidence threshold (0-1) for detection
        """
        # Load pre-trained models
        print(f"⚡ Loading Wake Word Models: {model_names}...")
        try:
            openwakeword.utils.download_models(model_names) # Ensure models are downloaded
            self.owwModel = Model(
                wakeword_models=model_names,
                inference_framework="onnx"
            )
            self.threshold = threshold
            self.buffer_size = 1280 # default chunk size usually
            print("✅ Wake Word Engine Ready")
        except Exception as e:
            print(f"❌ Failed to load Wake Word Engine: {e}")
            self.owwModel = None
            
    def detect(self, audio_chunk: np.ndarray) -> bool:
        """
        Process an audio chunk and check for wake word.
        
        Args:
            audio_chunk: Numpy array of audio samples (Int16, 16kHz)
        
        Returns:
            bool: True if wake word detected, False otherwise
        """
        if self.owwModel is None:
            return False
            
        # prediction = self.owwModel.predict(audio_chunk)
        # Predict returns a dict {model_name: score}
        
        # openwakeword expects 1280 samples typically, helps to be consistent or feed whatever
        # It handles buffering internally.
        
        try:
            # Predict
            prediction = self.owwModel.predict(audio_chunk)
            
            # Check scores
            for model, score in prediction.items():
                if score > 0.1: # Debug print for low scores too
                    pass # print(f"Wake Word Score ({model}): {score:.4f}")
                if score > self.threshold:
                    print(f"\n⚡ Wake Word Triggered: {model} ({score:.4f})")
                    self.owwModel.reset() # Reset state immediately after trigger
                    return True
                    
            return False
            
        except Exception as e:
            # print(f"Wake word error: {e}")
            return False

    def reset(self):
        """Reset the internal model state"""
        if self.owwModel:
            self.owwModel.reset()
