import os
from dotenv import load_dotenv

load_dotenv()

# General Settings
ENV = os.getenv("ENV", "development")
DEBUG = os.getenv("DEBUG", "true").lower() == "true"

# LLM Settings
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
LLM_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

# Safety Settings
HIGH_RISK_DEVICES = ["heater_1", "door_lock_1"]
QUIET_HOURS_START = "23:00"
QUIET_HOURS_END = "06:00"

# Learning Settings
LEARNING_INTERVAL_MINUTES = 60
HISTORY_LIMIT = 200
