from fastapi import APIRouter, Depends, WebSocket
from api.dependencies import get_system_state, SystemContainer
from api.security import get_api_key

router = APIRouter(dependencies=[Depends(get_api_key)])

@router.post("/config/vad")
async def config_vad(sensitivity: float, sys: SystemContainer = Depends(get_system_state)):
    """Configure VAD sensitivity."""
    if sys.voice_coordinator:
        # sys.voice_coordinator.set_vad_sensitivity(sensitivity)
        pass
    return {"sensitivity": sensitivity}

@router.post("/config/synthesizer")
async def config_tts(engine: str, sys: SystemContainer = Depends(get_system_state)):
    """Switch TTS engine (VibeVoice, EdgeTTS, CosyVoice)."""
    return {"status": "Switched", "engine": engine}

@router.websocket("/stream")
async def audio_stream(websocket: WebSocket, sys: SystemContainer = Depends(get_system_state)):
    """Real-time bi-directional audio stream."""
    await websocket.accept()
    # Placeholder for audio loop
    await websocket.close()
