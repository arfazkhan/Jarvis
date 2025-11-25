import unittest
import sys
from unittest.mock import MagicMock, patch

# Create mocks for optional dependencies
mock_whisper = MagicMock()
mock_sr = MagicMock()
mock_pyttsx3 = MagicMock()

class TestSTTEngine(unittest.TestCase):
    def setUp(self):
        # Patch sys.modules to simulate dependencies being present
        self.modules_patcher = patch.dict(sys.modules, {
            'whisper': mock_whisper,
            'speech_recognition': mock_sr
        })
        self.modules_patcher.start()
        
        # Re-import module to pick up mocked dependencies
        if 'agent_conversation.stt_engine' in sys.modules:
            del sys.modules['agent_conversation.stt_engine']
        import agent_conversation.stt_engine
        self.stt_module = agent_conversation.stt_engine

    def tearDown(self):
        self.modules_patcher.stop()

    def test_init_whisper(self):
        # Simulate Whisper available
        with patch.object(self.stt_module, 'WHISPER_AVAILABLE', True):
            engine = self.stt_module.STTEngine()
            mock_whisper.load_model.assert_called()
            self.assertIsNotNone(engine.model)

    def test_transcribe_fallback(self):
        # Simulate Whisper missing, SR available
        with patch.object(self.stt_module, 'WHISPER_AVAILABLE', False):
            with patch.object(self.stt_module, 'SR_AVAILABLE', True):
                engine = self.stt_module.STTEngine()
                
                # Mock recognizer
                mock_recognizer = MagicMock()
                engine.recognizer = mock_recognizer
                mock_recognizer.recognize_google.return_value = "hello world"
                
                result = engine._transcribe(MagicMock())
                self.assertEqual(result, "hello world")

class TestTTSEngine(unittest.TestCase):
    def setUp(self):
        self.modules_patcher = patch.dict(sys.modules, {
            'pyttsx3': mock_pyttsx3
        })
        self.modules_patcher.start()
        
        if 'agent_conversation.tts_engine' in sys.modules:
            del sys.modules['agent_conversation.tts_engine']
        import agent_conversation.tts_engine
        self.tts_module = agent_conversation.tts_engine

    def tearDown(self):
        self.modules_patcher.stop()

    def test_speak_queue(self):
        # Mock engine init
        mock_engine_instance = MagicMock()
        mock_pyttsx3.init.return_value = mock_engine_instance
        
        with patch.object(self.tts_module, 'TTS_AVAILABLE', True):
            engine = self.tts_module.TTSEngine()
            
            # Test non-blocking speak
            engine.speak("hello")
            
            # Queue should have item
            self.assertFalse(engine.queue.empty())
            
            # Clean up
            engine.stop()

    def test_speak_blocking(self):
        mock_engine_instance = MagicMock()
        mock_pyttsx3.init.return_value = mock_engine_instance
        
        with patch.object(self.tts_module, 'TTS_AVAILABLE', True):
            engine = self.tts_module.TTSEngine()
            
            # Test blocking speak
            engine.speak("hello", block=True)
            
            # Should call say and runAndWait
            mock_engine_instance.say.assert_called_with("hello")
            mock_engine_instance.runAndWait.assert_called()

if __name__ == "__main__":
    unittest.main()
