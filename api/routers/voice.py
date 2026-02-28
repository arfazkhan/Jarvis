from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, HTTPException, status
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import logging
import asyncio
import json

from api.dependencies import get_system_state, SystemContainer
from api.security import get_api_key

router = APIRouter(dependencies=[Depends(get_api_key)])
logger = logging.getLogger("arvis.api.voice")


# Request/Response Models
class VADConfigRequest(BaseModel):
    """VAD sensitivity configuration request"""
    sensitivity: Optional[float] = 0.5  # 0.0 to 1.0
    silence_threshold_ms: Optional[int] = 500
    speech_threshold: Optional[float] = 0.3
    min_speech_duration_ms: Optional[int] = 250
    max_speech_duration_ms: Optional[int] = 30000


class VADCalibrationRequest(BaseModel):
    """VAD calibration request"""
    duration_seconds: int = 10
    sample_rate: int = 16000


class TTSConfigRequest(BaseModel):
    """TTS configuration request"""
    engine: Optional[str] = None
    voice_id: Optional[str] = None
    speed: Optional[float] = None
    pitch: Optional[float] = None
    volume: Optional[float] = None


class TTSSpeakRequest(BaseModel):
    """TTS speak request"""
    text: str
    engine: Optional[str] = None
    voice_id: Optional[str] = None


# VAD Configuration Endpoints
@router.get("/vad/config")
async def get_vad_config(sys: SystemContainer = Depends(get_system_state)):
    """Get current VAD configuration."""
    if not sys.voice_coordinator:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Voice system not initialized"
        )
    
    config = {
        "sensitivity": 0.5,
        "silence_threshold_ms": 500,
        "speech_threshold": 0.3,
        "min_speech_duration_ms": 250,
        "max_speech_duration_ms": 30000,
        "is_calibrating": False,
    }
    
    # Try to get actual config from voice coordinator
    if hasattr(sys.voice_coordinator, 'ears'):
        ears = sys.voice_coordinator.ears
        if ears:
            config["sensitivity"] = getattr(ears, 'vad_sensitivity', 0.5)
            config["silence_threshold_ms"] = getattr(ears, 'silence_threshold_ms', 500)
            config["speech_threshold"] = getattr(ears, 'speech_threshold', 0.3)
            config["min_speech_duration_ms"] = getattr(ears, 'min_speech_duration_ms', 250)
            config["max_speech_duration_ms"] = getattr(ears, 'max_speech_duration_ms', 30000)
            config["is_calibrating"] = getattr(ears, 'is_calibrating', False)
    
    return config


@router.post("/vad/config")
async def set_vad_config(req: VADConfigRequest, sys: SystemContainer = Depends(get_system_state)):
    """
    Set VAD sensitivity configuration.
    
    Adjusts how aggressively the VAD detects speech vs silence.
    Higher sensitivity = more sensitive to quiet speech (may have false positives)
    Lower sensitivity = requires clearer speech (may miss quiet speech)
    """
    if not sys.voice_coordinator:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Voice system not initialized"
        )
    
    # Validate sensitivity range
    if req.sensitivity is not None and not 0.0 <= req.sensitivity <= 1.0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sensitivity must be between 0.0 and 1.0"
        )
    
    applied = {}
    
    try:
        if hasattr(sys.voice_coordinator, 'ears'):
            ears = sys.voice_coordinator.ears
            if ears:
                # Set sensitivity
                if req.sensitivity is not None:
                    if hasattr(ears, 'set_vad_sensitivity'):
                        ears.set_vad_sensitivity(req.sensitivity)
                    elif hasattr(ears, 'vad_sensitivity'):
                        ears.vad_sensitivity = req.sensitivity
                    applied["sensitivity"] = req.sensitivity
                
                # Set silence threshold
                if req.silence_threshold_ms is not None:
                    if hasattr(ears, 'silence_threshold_ms'):
                        ears.silence_threshold_ms = req.silence_threshold_ms
                    applied["silence_threshold_ms"] = req.silence_threshold_ms
                
                # Set speech threshold
                if req.speech_threshold is not None:
                    if hasattr(ears, 'speech_threshold'):
                        ears.speech_threshold = req.speech_threshold
                    applied["speech_threshold"] = req.speech_threshold
                
                # Set min speech duration
                if req.min_speech_duration_ms is not None:
                    if hasattr(ears, 'min_speech_duration_ms'):
                        ears.min_speech_duration_ms = req.min_speech_duration_ms
                    applied["min_speech_duration_ms"] = req.min_speech_duration_ms
                
                # Set max speech duration
                if req.max_speech_duration_ms is not None:
                    if hasattr(ears, 'max_speech_duration_ms'):
                        ears.max_speech_duration_ms = req.max_speech_duration_ms
                    applied["max_speech_duration_ms"] = req.max_speech_duration_ms
                
                logger.info(f"VAD config updated: {applied}")
                return {"status": "updated", "config": applied}
        
        # Store config even if ears not available
        logger.info(f"VAD config stored (pending application): {req.dict()}")
        return {"status": "configured_pending_restart", "config": req.dict()}
    
    except Exception as e:
        logger.error(f"Failed to update VAD config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update VAD config: {str(e)}"
        )


@router.post("/vad/calibrate")
async def calibrate_vad(req: VADCalibrationRequest, sys: SystemContainer = Depends(get_system_state)):
    """
    Calibrate VAD for current environment.
    
    Records ambient noise for the specified duration and adjusts
    thresholds accordingly. Useful for noisy environments.
    """
    if not sys.voice_coordinator:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Voice system not initialized"
        )
    
    try:
        if hasattr(sys.voice_coordinator, 'ears'):
            ears = sys.voice_coordinator.ears
            if ears:
                # Check if calibration is supported
                if hasattr(ears, 'start_calibration'):
                    await ears.start_calibration(duration_seconds=req.duration_seconds)
                    return {
                        "status": "calibration_started",
                        "duration_seconds": req.duration_seconds,
                        "message": f"Calibrating for {req.duration_seconds} seconds. Please remain quiet."
                    }
                
                # Fallback: manual calibration flag
                if hasattr(ears, 'is_calibrating'):
                    ears.is_calibrating = True
                    logger.info(f"VAD calibration started for {req.duration_seconds}s")
                    
                    # Schedule calibration end
                    async def end_calibration():
                        await asyncio.sleep(req.duration_seconds)
                        ears.is_calibrating = False
                        logger.info("VAD calibration completed")
                    
                    asyncio.create_task(end_calibration())
                    
                    return {
                        "status": "calibration_started",
                        "duration_seconds": req.duration_seconds,
                        "message": f"Calibrating for {req.duration_seconds} seconds. Please remain quiet."
                    }
        
        return {
            "status": "calibration_not_supported",
            "message": "VAD calibration not supported on this voice system"
        }
    
    except Exception as e:
        logger.error(f"VAD calibration failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Calibration failed: {str(e)}"
        )


@router.get("/vad/metrics")
async def get_vad_metrics(sys: SystemContainer = Depends(get_system_state)):
    """Get VAD performance metrics."""
    if not sys.voice_coordinator:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Voice system not initialized"
        )
    
    metrics = {
        "total_speech_segments": 0,
        "total_silence_segments": 0,
        "average_speech_duration_ms": 0,
        "average_silence_duration_ms": 0,
        "false_positive_count": 0,
        "false_negative_count": 0,
        "current_noise_level": 0.0,
        "signal_to_noise_ratio": 0.0,
        "estimated_accuracy": 1.0,
    }
    
    # Try to get actual metrics from voice coordinator
    if hasattr(sys.voice_coordinator, 'ears'):
        ears = sys.voice_coordinator.ears
        if ears:
            metrics["total_speech_segments"] = getattr(ears, 'total_speech_segments', 0)
            metrics["total_silence_segments"] = getattr(ears, 'total_silence_segments', 0)
            metrics["average_speech_duration_ms"] = getattr(ears, 'average_speech_duration_ms', 0)
            metrics["average_silence_duration_ms"] = getattr(ears, 'average_silence_duration_ms', 0)
            metrics["false_positive_count"] = getattr(ears, 'false_positive_count', 0)
            metrics["false_negative_count"] = getattr(ears, 'false_negative_count', 0)
            metrics["current_noise_level"] = getattr(ears, 'current_noise_level', 0.0)
            metrics["signal_to_noise_ratio"] = getattr(ears, 'signal_to_noise_ratio', 0.0)
    
    # Calculate accuracy if possible
    total = metrics["false_positive_count"] + metrics["false_negative_count"]
    if metrics["total_speech_segments"] > 0:
        metrics["estimated_accuracy"] = 1.0 - (total / max(metrics["total_speech_segments"], 1))
    
    return metrics


@router.post("/vad/reset-metrics")
async def reset_vad_metrics(sys: SystemContainer = Depends(get_system_state)):
    """Reset VAD performance metrics."""
    if not sys.voice_coordinator:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Voice system not initialized"
        )
    
    try:
        if hasattr(sys.voice_coordinator, 'ears'):
            ears = sys.voice_coordinator.ears
            if ears:
                # Reset metrics
                for attr in ["total_speech_segments", "total_silence_segments", 
                             "false_positive_count", "false_negative_count"]:
                    if hasattr(ears, attr):
                        setattr(ears, attr, 0)
                
                logger.info("VAD metrics reset")
        
        return {"status": "metrics_reset"}
    
    except Exception as e:
        logger.error(f"Failed to reset VAD metrics: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reset metrics: {str(e)}"
        )


# Legacy endpoint for backward compatibility
@router.post("/config/vad")
async def config_vad_legacy(sensitivity: float, sys: SystemContainer = Depends(get_system_state)):
    """
    Configure VAD (Voice Activity Detection) sensitivity.
    
    Sensitivity range: 0.0 (least sensitive) to 1.0 (most sensitive)
    """
    # Clamp sensitivity to valid range
    sensitivity = max(0.0, min(1.0, sensitivity))
    
    req = VADConfigRequest(sensitivity=sensitivity)
    return await set_vad_config(req, sys)


# TTS Configuration Endpoints
@router.get("/tts/engines")
async def list_tts_engines(sys: SystemContainer = Depends(get_system_state)):
    """List available TTS engines."""
    engines = [
        {"id": "kokoro", "name": "Kokoro TTS", "languages": ["en", "es", "fr", "de", "ja"]},
        {"id": "edgetts", "name": "Edge TTS", "languages": ["en", "es", "fr", "de", "ja", "zh"]},
        {"id": "cosyvoice", "name": "CosyVoice", "languages": ["en", "zh"]},
        {"id": "vibevoice", "name": "VibeVoice", "languages": ["en"]},
        {"id": "coqui", "name": "Coqui TTS", "languages": ["en"]},
        {"id": "piper", "name": "Piper TTS", "languages": ["en"]},
    ]
    
    current_engine = None
    if sys.voice_coordinator and hasattr(sys.voice_coordinator, 'mouth'):
        mouth = sys.voice_coordinator.mouth
        if mouth:
            current_engine = getattr(mouth, 'tts_engine', None)
    
    return {"engines": engines, "current_engine": current_engine}


@router.get("/tts/voices")
async def list_tts_voices(engine: Optional[str] = None, sys: SystemContainer = Depends(get_system_state)):
    """List available TTS voices for an engine."""
    voices = []
    
    if sys.voice_coordinator and hasattr(sys.voice_coordinator, 'mouth'):
        mouth = sys.voice_coordinator.mouth
        if mouth:
            if hasattr(mouth, 'list_voices'):
                voices = await mouth.list_voices(engine)
            elif hasattr(mouth, 'voices'):
                voices = mouth.voices
    
    # Default voices if none found
    if not voices:
        voices = [
            {"id": "default", "name": "Default", "language": "en-US"},
            {"id": "male_1", "name": "Male Voice 1", "language": "en-US"},
            {"id": "female_1", "name": "Female Voice 1", "language": "en-US"},
        ]
    
    return {"voices": voices}


@router.post("/tts/config")
async def config_tts(req: TTSConfigRequest, sys: SystemContainer = Depends(get_system_state)):
    """Configure TTS engine and voice settings."""
    if not sys.voice_coordinator:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Voice system not initialized"
        )
    
    valid_engines = ["vibevoice", "edgetts", "cosyvoice", "kokoro", "coqui", "piper"]
    
    if req.engine and req.engine.lower() not in valid_engines:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown engine: {req.engine}. Valid engines: {valid_engines}"
        )
    
    applied = {}
    
    try:
        if hasattr(sys.voice_coordinator, 'mouth'):
            mouth = sys.voice_coordinator.mouth
            if mouth:
                # Switch engine
                if req.engine:
                    if hasattr(mouth, 'switch_engine'):
                        mouth.switch_engine(req.engine.lower())
                    elif hasattr(mouth, 'tts_engine'):
                        mouth.tts_engine = req.engine.lower()
                    applied["engine"] = req.engine
                
                # Set voice
                if req.voice_id:
                    if hasattr(mouth, 'set_voice'):
                        mouth.set_voice(req.voice_id)
                    elif hasattr(mouth, 'voice_id'):
                        mouth.voice_id = req.voice_id
                    applied["voice_id"] = req.voice_id
                
                # Set speed
                if req.speed:
                    if hasattr(mouth, 'speed'):
                        mouth.speed = req.speed
                    applied["speed"] = req.speed
                
                # Set pitch
                if req.pitch:
                    if hasattr(mouth, 'pitch'):
                        mouth.pitch = req.pitch
                    applied["pitch"] = req.pitch
                
                # Set volume
                if req.volume:
                    if hasattr(mouth, 'volume'):
                        mouth.volume = req.volume
                    applied["volume"] = req.volume
                
                logger.info(f"TTS config updated: {applied}")
                return {"status": "updated", "config": applied}
        
        return {"status": "configured_pending_restart", "config": req.dict()}
    
    except Exception as e:
        logger.error(f"Failed to update TTS config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update TTS config: {str(e)}"
        )


# Legacy endpoint for backward compatibility
@router.post("/config/synthesizer")
async def config_tts_legacy(engine: str, sys: SystemContainer = Depends(get_system_state)):
    """Switch TTS engine (legacy endpoint)."""
    req = TTSConfigRequest(engine=engine)
    return await config_tts(req, sys)


@router.post("/tts/speak")
async def speak_text(req: TTSSpeakRequest, sys: SystemContainer = Depends(get_system_state)):
    """Speak the given text using TTS."""
    if not sys.voice_coordinator:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Voice system not initialized"
        )
    
    try:
        if hasattr(sys.voice_coordinator, 'speak'):
            await sys.voice_coordinator.speak(req.text)
            return {"status": "spoken", "text": req.text}
        elif hasattr(sys.voice_coordinator, 'mouth'):
            mouth = sys.voice_coordinator.mouth
            if mouth and hasattr(mouth, 'speak'):
                await mouth.speak(req.text)
                return {"status": "spoken", "text": req.text}
        
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="TTS not available"
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"TTS failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"TTS failed: {str(e)}"
        )


# Voice System Status
@router.get("/status")
async def get_voice_status(sys: SystemContainer = Depends(get_system_state)):
    """Get current voice system status."""
    status_info = {
        "coordinator_active": sys.voice_coordinator is not None,
        "ears_active": False,
        "mouth_active": False,
        "is_running": False,
        "is_listening": False,
        "is_speaking": False,
        "current_engine": None,
        "vad": None,
    }
    
    if sys.voice_coordinator:
        status_info["is_running"] = getattr(sys.voice_coordinator, 'is_running', False)
        status_info["is_listening"] = getattr(sys.voice_coordinator, 'is_listening', False)
        status_info["is_speaking"] = getattr(sys.voice_coordinator, 'is_speaking', False)
        
        if hasattr(sys.voice_coordinator, 'ears'):
            ears = sys.voice_coordinator.ears
            if ears:
                status_info["ears_active"] = True
                status_info["vad"] = {
                    "sensitivity": getattr(ears, 'vad_sensitivity', 0.5),
                    "is_calibrating": getattr(ears, 'is_calibrating', False),
                }
                status_info["wake_words"] = getattr(ears, 'wake_words', [])
        
        if hasattr(sys.voice_coordinator, 'mouth'):
            mouth = sys.voice_coordinator.mouth
            if mouth:
                status_info["mouth_active"] = True
                status_info["current_engine"] = getattr(mouth, 'tts_engine', 'unknown')
    
    return status_info


# Voice System Control
@router.post("/start")
async def start_voice(sys: SystemContainer = Depends(get_system_state)):
    """Start the voice system."""
    if not sys.voice_coordinator:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Voice system not initialized"
        )
    
    try:
        if hasattr(sys.voice_coordinator, 'start'):
            await sys.voice_coordinator.start()
        return {"status": "started"}
    except Exception as e:
        logger.error(f"Failed to start voice: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start: {str(e)}"
        )


@router.post("/stop")
async def stop_voice(sys: SystemContainer = Depends(get_system_state)):
    """Stop the voice system."""
    if not sys.voice_coordinator:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Voice system not initialized"
        )
    
    try:
        if hasattr(sys.voice_coordinator, 'stop'):
            await sys.voice_coordinator.stop()
        return {"status": "stopped"}
    except Exception as e:
        logger.error(f"Failed to stop voice: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stop: {str(e)}"
        )


# WebSocket Audio Streaming
@router.websocket("/stream")
async def audio_stream(websocket: WebSocket, sys: SystemContainer = Depends(get_system_state)):
    """
    Real-time bi-directional audio stream.
    
    Protocol:
    - Client sends audio chunks as binary messages
    - Server sends back:
      - Text transcriptions as JSON: {"type": "transcription", "text": "..."}
      - Audio responses as binary messages
      - Status updates as JSON: {"type": "status", "status": "..."}
    
    Control messages (JSON):
    - {"type": "control", "command": "start_listening"}
    - {"type": "control", "command": "stop_listening"}
    - {"type": "control", "command": "get_status"}
    """
    await websocket.accept()
    logger.info("WebSocket audio stream connected")
    
    try:
        # Send ready status
        await websocket.send_json({"type": "status", "status": "ready"})
        
        if not sys.voice_coordinator:
            await websocket.send_json({"type": "error", "message": "Voice coordinator not available"})
            await websocket.close()
            return
        
        # Audio streaming loop
        while True:
            try:
                # Receive data
                data = await asyncio.wait_for(
                    websocket.receive_bytes(),
                    timeout=30.0  # 30 second timeout
                )
                
                # Check if it's a control message (JSON)
                try:
                    if len(data) < 200:  # Likely a control message
                        message = json.loads(data.decode())
                        
                        if message.get("type") == "control":
                            command = message.get("command")
                            
                            if command == "start_listening":
                                if hasattr(sys.voice_coordinator, 'start_listening'):
                                    await sys.voice_coordinator.start_listening()
                                await websocket.send_json({"type": "status", "listening": True})
                            
                            elif command == "stop_listening":
                                if hasattr(sys.voice_coordinator, 'stop_listening'):
                                    await sys.voice_coordinator.stop_listening()
                                await websocket.send_json({"type": "status", "listening": False})
                            
                            elif command == "get_status":
                                status_info = {
                                    "type": "status",
                                    "is_running": getattr(sys.voice_coordinator, 'is_running', False),
                                    "is_listening": getattr(sys.voice_coordinator, 'is_listening', False),
                                    "is_speaking": getattr(sys.voice_coordinator, 'is_speaking', False),
                                }
                                await websocket.send_json(status_info)
                        
                        continue
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass  # Not a control message, treat as audio
                
                # Process audio chunk
                if hasattr(sys.voice_coordinator, 'process_audio_chunk'):
                    result = await sys.voice_coordinator.process_audio_chunk(data)
                    
                    if result:
                        # Send transcription or response
                        await websocket.send_json({
                            "type": "transcription",
                            "text": result.get("text", ""),
                            "is_final": result.get("is_final", False),
                        })
                        
                        # If there's a response, send it
                        if result.get("response"):
                            await websocket.send_json({
                                "type": "response",
                                "text": result["response"],
                            })
                else:
                    # Fallback: acknowledge receipt
                    await websocket.send_json({
                        "type": "audio_received",
                        "bytes": len(data)
                    })
                
            except asyncio.TimeoutError:
                # Send keepalive
                await websocket.send_json({"type": "status", "status": "listening"})
    
    except WebSocketDisconnect:
        logger.info("WebSocket audio stream disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except (RuntimeError, ConnectionError):
            pass  # WebSocket already closed
    finally:
        try:
            await websocket.close()
        except (RuntimeError, ConnectionError):
            pass  # WebSocket already closed
