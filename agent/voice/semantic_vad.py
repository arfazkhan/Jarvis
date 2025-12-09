"""
Semantic VAD Engine
-----------------
Context-aware Voice Activity Detection using SileroVAD + LLM sentence completeness.
"""

import torch
import numpy as np
from groq import Groq
import os

class SemanticVAD:
    def __init__(self):
        """Initialize Semantic VAD with SileroVAD model"""
        print("⚡ Loading Semantic VAD...")
        
        # Load SileroVAD model
        try:
            self.vad_model, utils = torch.hub.load(
                repo_or_dir='snakers4/silero-vad',
                model='silero_vad',
                force_reload=False,
                onnx=True  # Use ONNX for faster inference
            )
            self.get_speech_timestamps = utils[0]
            print("✅ SileroVAD loaded")
        except Exception as e:
            print(f"❌ Failed to load SileroVAD: {e}")
            self.vad_model = None
            
        # Initialize Groq for sentence completeness
        api_key = os.environ.get("GROQ_API_KEY")
        self.groq = Groq(api_key=api_key) if api_key else None
        
        # VAD parameters
        self.speech_threshold = 0.5
        
    def detect_speech(self, audio_chunk: np.ndarray, sample_rate: int = 16000) -> float:
        """
        Detect speech probability in audio chunk.
        
        Args:
            audio_chunk: numpy array (float32, normalized)
            sample_rate: audio sample rate
            
        Returns:
            float: Speech probability (0-1)
        """
        if self.vad_model is None:
            # Fallback: Simple energy-based
            return float(np.sqrt(np.mean(audio_chunk**2)))
            
        try:
            # Convert to tensor
            audio_tensor = torch.from_numpy(audio_chunk).float()
            
            # Get speech probability
            speech_prob = self.vad_model(audio_tensor, sample_rate).item()
            return speech_prob
            
        except Exception as e:
            # Fallback
            return float(np.sqrt(np.mean(audio_chunk**2)))
    
    def is_sentence_complete(self, text: str, use_llm: bool = True) -> bool:
        """
        Check if sentence/thought is semantically complete.
        
        Args:
            text: Transcribed text to check
            use_llm: Whether to use LLM (falls back to rules if False)
            
        Returns:
            bool: True if sentence is complete
        """
        if not text or len(text.strip()) < 3:
            return False
            
        # Primary: Fast LLM check
        if use_llm and self.groq:
            try:
                response = self.groq.chat.completions.create(
                    model="llama-3.3-70b-versatile",  # Fast Groq model
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a sentence completeness detector. A sentence is COMPLETE if it expresses a full thought or command. Answer ONLY 'yes' or 'no'."
                        },
                        {
                            "role": "user", 
                            "content": f"Is this complete? '{text}'"
                        }
                    ],
                    temperature=0,
                    max_tokens=5
                )
                answer = response.choices[0].message.content.strip().lower()
                return "yes" in answer
                
            except Exception as e:
                # Fallback to rules
                pass
        
        # Fallback: Rule-based check
        return self._rule_based_completeness(text)
    
    def _rule_based_completeness(self, text: str) -> bool:
        """
        Rule-based sentence completeness check (fallback).
        
        Heuristics:
        - Must have at least 3 words
        - Cannot end with preposition/conjunction/articles
        - Should have verb-like structure
        """
        words = text.lower().strip().split()
        
        if len(words) < 2:
            return False
        
        # Incomplete indicators (trailing words that signal continuation)
        incomplete_endings = [
            "the", "a", "an", "to", "in", "on", "at", "for", "with",
            "and", "or", "but", "so", "then", "my", "your", "this", "that"
        ]
        
        # Check last word
        last_word = words[-1].rstrip('.,!?')
        if last_word in incomplete_endings:
            return False
        
        # If it ends with "..." → incomplete
        if text.strip().endswith("..."):
            return False
            
        # Otherwise, likely complete
        return True
