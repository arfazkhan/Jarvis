"""
Voice Transcriber
----------------
Handles audio transcription using Groq's Whisper API.
"""

import os
from groq import Groq

class VoiceTranscriber:
    def __init__(self):
        """Initialize Groq client for transcription"""
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            print("[VoiceTranscriber] Warning: GROQ_API_KEY not found in environment")
        self.client = Groq(api_key=api_key)

    def transcribe(self, file_path: str) -> str:
        """
        Transcribe audio file to text using Whisper-large-v3.
        
        Args:
            file_path: Path to the audio file
            
        Returns:
            str: Transcribed text
        """
        try:
            if not os.path.exists(file_path):
                return f"Error: File not found at {file_path}"
                
            with open(file_path, "rb") as file:
                transcription = self.client.audio.transcriptions.create(
                  file=(file_path, file.read()),
                  model="whisper-large-v3",
                  temperature=0,
                  response_format="verbose_json",
                )
                return transcription.text
                
        except Exception as e:
            print(f"[VoiceTranscriber] Error: {e}")
            return f"Error authenticating or processing audio: {str(e)}"
