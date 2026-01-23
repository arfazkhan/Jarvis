"""
ESP RainMaker Local Control Client
===================================
Controls ESP RainMaker devices over local network using the esp_local_ctrl protocol.

The ESP RainMaker local control uses a protobuf-based protocol over HTTP.
For simplicity, we'll use the mDNS service discovery and HTTP POST.

Device info from logs:
- Node ID: XsG36uJUovRVia4tbvmPau
- IP: 192.168.1.20
- Port: 8080
- POP: f02cc62d (Proof of Possession for security)
"""

import json
import socket
import struct
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RainMakerDevice:
    """Represents an ESP RainMaker device."""
    node_id: str
    ip: str
    port: int = 8080
    pop: Optional[str] = None  # Proof of Possession
    

class RainMakerLocalClient:
    """
    Client for controlling ESP RainMaker devices via local network.
    
    The esp_local_ctrl protocol uses a simple request/response format.
    """
    
    def __init__(self, device: RainMakerDevice):
        self.device = device
        self.session_id = None
        self._connected = False
        
    def connect(self) -> bool:
        """Establish connection to the device."""
        try:
            # Test if device is reachable
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex((self.device.ip, self.device.port))
            sock.close()
            
            if result == 0:
                self._connected = True
                logger.info(f"[RainMaker] Connected to {self.device.ip}:{self.device.port}")
                return True
            else:
                logger.warning(f"[RainMaker] Cannot reach {self.device.ip}:{self.device.port}")
                return False
        except Exception as e:
            logger.error(f"[RainMaker] Connection error: {e}")
            return False
    
    def set_param(self, device_name: str, param_name: str, value: Any) -> bool:
        """
        Set a parameter on the device.
        
        For the LED example:
        - device_name: "Light"
        - param_name: "Power" (bool), "Brightness" (0-100), "Hue" (0-360), "Saturation" (0-100)
        """
        try:
            # The local control uses a custom protocol
            # For now, we'll use the REST API if available
            import requests
            
            # Try different endpoints
            endpoints = [
                f"http://{self.device.ip}:{self.device.port}/esp_local_ctrl/control",
                f"http://{self.device.ip}:{self.device.port}/ctrl",
            ]
            
            payload = {
                device_name: {
                    param_name: value
                }
            }
            
            for endpoint in endpoints:
                try:
                    response = requests.post(
                        endpoint,
                        json=payload,
                        timeout=5,
                        verify=False
                    )
                    if response.ok:
                        logger.info(f"[RainMaker] Set {device_name}.{param_name} = {value}")
                        return True
                except:
                    continue
            
            logger.warning(f"[RainMaker] Failed to set parameter via HTTP")
            return False
            
        except Exception as e:
            logger.error(f"[RainMaker] Error setting param: {e}")
            return False
    
    def turn_on(self) -> bool:
        """Turn the light on."""
        return self.set_param("Light", "Power", True)
    
    def turn_off(self) -> bool:
        """Turn the light off."""
        return self.set_param("Light", "Power", False)
    
    def set_brightness(self, level: int) -> bool:
        """Set brightness (0-100)."""
        level = max(0, min(100, level))
        return self.set_param("Light", "Brightness", level)
    
    def set_color(self, hue: int, saturation: int = 100) -> bool:
        """Set color (hue: 0-360, saturation: 0-100)."""
        self.set_param("Light", "Hue", hue)
        return self.set_param("Light", "Saturation", saturation)


# Quick test function
def test_rainmaker_device():
    """Test connection to the ESP RainMaker device."""
    device = RainMakerDevice(
        node_id="XsG36uJUovRVia4tbvmPau",
        ip="192.168.1.20",
        port=8080,
        pop="f02cc62d"
    )
    
    client = RainMakerLocalClient(device)
    
    print(f"Testing connection to {device.ip}:{device.port}...")
    if client.connect():
        print("✅ Device reachable!")
        print("\nTrying to turn on light...")
        if client.turn_on():
            print("✅ Light turned on!")
        else:
            print("❌ Could not control via HTTP (protocol mismatch)")
            print("\nNote: ESP RainMaker local control uses esp_local_ctrl protocol")
            print("which requires the official SDK or protobuf implementation.")
    else:
        print("❌ Device not reachable")


if __name__ == "__main__":
    test_rainmaker_device()
