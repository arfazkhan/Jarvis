"""
Enhanced configuration system for Home Agent
Supports all 7 phases with privacy, security, and performance settings
"""

import os
from pathlib import Path
from typing import Dict, Any
from dotenv import load_dotenv

load_dotenv()

# Base paths
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "agent" / "logs"

# Core settings
ENV = os.getenv("ENV", "development")
DEBUG = os.getenv("DEBUG", "true").lower() == "true"
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# ============================================================================
# PHASE 1: Cognitive Layer Settings
# ============================================================================
COGNITIVE_CONFIG = {
    "memory": {
        "storage_path": DATA_DIR / "memory" / "events.db",
        "retention_days_raw": 90,  # Raw events kept for 90 days
        "retention_days_summaries": 365 * 3,  # Summaries kept for 3 years
        "compaction_interval_hours": 24,
        "max_history_limit": 200,
    },
    "embeddings": {
        "model": "sentence-transformers/all-MiniLM-L6-v2",
        "vector_store": "faiss",  # or "chromadb"
        "embedding_dim": 384,
        "similarity_threshold": 0.7,
        "pii_redaction_enabled": True,
    },
    "context_graph": {
        "storage_path": DATA_DIR / "cognitive" / "context_graph.json",
        "max_depth": 3,
        "time_window_days": 30,
    },
    "prediction": {
        "confidence_threshold": 0.70,  # Only suggest if >= 70% confidence
        "risk_threshold": 0.30,  # High risk if >= 30%
        "enable_auto_execution": False,  # Safety: require approval
        "target_precision": 0.70,  # Goal: 70% precision@1
    },
    "cognitive_loop": {
        "interval_minutes": 10,
        "enabled": True,
    },
}

# ============================================================================
# PHASE 2: Natural Interaction Settings
# ============================================================================
CONVERSATION_CONFIG = {
    "dialogue": {
        "session_timeout_minutes": 30,
        "context_window_turns": 10,
        "max_session_history": 100,
    },
    "sentiment": {
        "model": "textblob",  # or "distilbert-base-uncased-finetuned-sst-2-english"
        "confidence_threshold": 0.6,
        "emotion_buckets": ["tired", "happy", "annoyed", "neutral"],
    },
    "stt": {
        "engine": "whisper",  # whisper, vosk, google_cloud
        "whisper_model": "base",  # tiny, base, small, medium, large
        "language": "en",
        "sample_rate": 16000,
    },
    "tts": {
        # TTS engine: "edgetts", "vibevoice", "cosyvoice", "kokoro", "coqui", or "piper"
        # Set via TTS_ENGINE environment variable
        "engine": os.getenv("TTS_ENGINE", "vibevoice"),
        
        # Edge TTS settings (if TTS_ENGINE=edgetts) - cloud-based, free, no API key
        "edgetts_voice": os.getenv("EDGETTS_VOICE", "guy"),  # guy, jenny, aria, davis, neerja, prabhat, etc.
        "edgetts_rate": os.getenv("EDGETTS_RATE", "+0%"),  # Speech rate: "+10%", "-20%"
        
        # VibeVoice-specific settings (if TTS_ENGINE=vibevoice)
        "vibevoice_model": os.getenv("VIBEVOICE_MODEL", "microsoft/VibeVoice-Realtime-0.5B"),
        "vibevoice_device": os.getenv("VIBEVOICE_DEVICE", "cuda"),
        "vibevoice_speaker": os.getenv("VIBEVOICE_SPEAKER", "carter"),  # carter, davis, emma, frank, grace, mike
        
        # CosyVoice-specific settings (if TTS_ENGINE=cosyvoice)
        "cosyvoice_model": os.getenv("COSYVOICE_MODEL", "Fun-CosyVoice3-0.5B"),  # Latest 0.5B, fits 4GB GPU
        "cosyvoice_device": os.getenv("COSYVOICE_DEVICE", "cuda"),  # "cuda" or "cpu"
        "cosyvoice_speaker": os.getenv("COSYVOICE_SPEAKER", "英文女"),  # English female default
        
        # General TTS settings
        "rate": 150,  # Words per minute
        "volume": 0.9,
    },
    "privacy": {
        "store_audio": False,  # Don't store audio by default
        "store_transcripts_days": 30,
        "scrub_pii_before_llm": True,
    },
}

# ============================================================================
# PHASE 3: Planning Settings
# ============================================================================
PLANNING_CONFIG = {
    "plan_generator": {
        "max_steps": 20,
        "max_parallel_steps": 5,
        "timeout_seconds": 30,
    },
    "plan_validator": {
        "enable_conflict_detection": True,
        "enable_rate_limiting": True,
        "enable_high_risk_checks": True,
        "rejection_threshold": 0.95,  # Reject if conflict confidence >= 95%
    },
    "plan_executor": {
        "max_retries": 3,
        "retry_backoff_seconds": [1, 5, 15],  # Exponential backoff
        "enable_compensation": True,  # Rollback on failure
        "dry_run_mode": False,
    },
}

# ============================================================================
# PHASE 4: Sensor Fusion Settings
# ============================================================================
SENSOR_CONFIG = {
    "virtual_sensors": {
        "enabled": True,  # Use virtual sensors for development
        "noise_level": 0.1,  # 10% noise in simulated sensors
        "update_interval_seconds": 5,
    },
    "presence_model": {
        "algorithm": "bayesian",  # bayesian or heuristic
        "confidence_threshold": 0.8,
        "hysteresis_seconds": 300,  # 5 min buffer to avoid flicker
    },
    "state_estimator": {
        "inference_latency_ms_target": 100,
        "enable_noise_filtering": True,
    },
}

# ============================================================================
# PHASE 5: Personality Settings
# ============================================================================
PERSONALITY_CONFIG = {
    "profiles": {
        "default_user": {
            "humor": "medium",  # low, medium, high
            "directness": "neutral",  # soft, neutral, blunt
            "formality": "casual",  # casual, neutral, formal
            "verbosity": "normal",  # short, normal, detailed
            "context_tags": [],  # e.g., ["night_owl", "builder"]
        },
    },
    "emotional_state": {
        "update_interval_minutes": 5,
        "sentiment_weight": 0.5,
        "command_frequency_weight": 0.3,
        "late_night_activity_weight": 0.2,
    },
    "tone_adapter": {
        "enabled": True,
        "safety_override": True,  # Emergency messages ignore persona
    },
    "privacy": {
        "opt_in_required": True,
        "allow_cloud_export": False,
    },
}

# ============================================================================
# PHASE 6: Mission Settings
# ============================================================================
MISSION_CONFIG = {
    "mission_executor": {
        "checkpoint_interval_minutes": 10,
        "max_concurrent_missions": 5,
        "enable_recovery": True,
    },
    "mission_templates": {
        "vacation_mode": {
            "goals": ["reduce_energy", "simulate_presence", "security"],
            "duration_days": 7,
        },
        "sleep_optimization": {
            "goals": ["better_sleep", "wake_comfort"],
            "duration_days": 30,
        },
        "energy_saving": {
            "goals": ["reduce_cost", "reduce_carbon"],
            "duration_days": 30,
        },
    },
    "safety": {
        "allow_high_risk_actions": False,
        "require_approval_for_locks": True,
        "require_approval_for_garage": True,
    },
}

# ============================================================================
# PHASE 7: Web UI Settings
# ============================================================================
WEB_UI_CONFIG = {
    "server": {
        "host": "127.0.0.1",  # Localhost only (security)
        "port": 5000,
        "debug": DEBUG,
        "enable_cors": False,  # Only enable if needed
    },
    "reasoning_log": {
        "max_entries": 10000,
        "retention_days": 90,
        "enable_full_debug_mode": False,  # Sensitive PII included
    },
    "authentication": {
        "enabled": False,  # Enable for production
        "token_secret": os.getenv("WEB_UI_SECRET", "change-me-in-production"),
    },
    "real_time": {
        "enable_websocket": True,
        "update_interval_seconds": 2,
    },
}

# ============================================================================
# Cross-Phase NFRs (Non-Functional Requirements)
# ============================================================================
SECURITY_CONFIG = {
    "local_first": True,  # All data local by default
    "cloud_llm_opt_in": False,  # Explicit opt-in required
    "high_risk_devices": ["lock", "garage_door", "alarm"],
    "allowlist_per_user": {},  # User-specific allowlist for high-risk devices
}

PRIVACY_CONFIG = {
    "enable_export": True,  # GDPR export
    "enable_delete": True,  # GDPR delete
    "pii_fields": ["name", "email", "phone", "address", "location"],
}

PERFORMANCE_CONFIG = {
    "targets": {
        "event_to_state_update_ms": 50,  # p99
        "api_response_ms": 200,  # p95
        "embedding_lookup_ms": 50,  # p95
        "sensor_inference_ms": 100,  # p95
    },
    "rate_limiting": {
        "enabled": True,
        "min_interval_ms": 500,  # Min 500ms between endpoint calls
    },
}

OBSERVABILITY_CONFIG = {
    "logging": {
        "level": "DEBUG" if DEBUG else "INFO",
        "format": "json",  # json or text
        "output": str(LOGS_DIR / "agent.log"),
    },
    "metrics": {
        "enabled": True,
        "prometheus_port": 9090,
    },
    "tracing": {
        "enabled": True,
        "include_trace_ids": True,
    },
}

# ============================================================================
# Helper functions
# ============================================================================
def get_config(phase: str) -> Dict[str, Any]:
    """Get configuration for a specific phase"""
    config_map = {
        "cognitive": COGNITIVE_CONFIG,
        "conversation": CONVERSATION_CONFIG,
        "planning": PLANNING_CONFIG,
        "sensors": SENSOR_CONFIG,
        "personality": PERSONALITY_CONFIG,
        "missions": MISSION_CONFIG,
        "web_ui": WEB_UI_CONFIG,
    }
    return config_map.get(phase, {})

def validate_config():
    """Validate that all required settings are present"""
    errors = []
    
    if not GROQ_API_KEY and ENV == "production":
        errors.append("GROQ_API_KEY not set in production environment")
    
    # Ensure data directories exist
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    
    if errors:
        raise ValueError(f"Configuration errors: {', '.join(errors)}")

# Run validation on import
validate_config()
