"""ArvisX ingest layer — turns fragmented device signals into AssetStore readings.

Phase 2: MQTT (the IoT lingua franca). Modbus/BACnet/REST follow the same shape:
parse a transport message → (asset_id, signal_key, value) → AssetStore.apply_reading.
The parse + handle logic is PURE (testable with no broker); the transport client is
a thin shell around it.
"""
