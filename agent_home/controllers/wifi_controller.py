import requests
import logging

logger = logging.getLogger(__name__)

class WifiController:
    def __init__(self):
        pass

    def turn_on(self, endpoint: str):
        """Turn on the device via HTTP POST."""
        url = f"{endpoint}/switch/relay_1/turn_on"
        try:
            response = requests.post(url, timeout=5)
            response.raise_for_status()
            logger.info(f"Turned ON {endpoint}")
            return True
        except Exception as e:
            logger.error(f"Failed to turn ON {endpoint}: {e}")
            return False

    def turn_off(self, endpoint: str):
        """Turn off the device via HTTP POST."""
        url = f"{endpoint}/switch/relay_1/turn_off"
        try:
            response = requests.post(url, timeout=5)
            response.raise_for_status()
            logger.info(f"Turned OFF {endpoint}")
            return True
        except Exception as e:
            logger.error(f"Failed to turn OFF {endpoint}: {e}")
            return False

    def get_status(self, endpoint: str):
        """Get device status (mocked for now as ESPHome simple API is fire-and-forget)."""
        # Real implementation would parse /status or /sensor
        # For this example, we just ping
        try:
            response = requests.get(endpoint, timeout=2)
            return response.status_code == 200
        except:
            return False
