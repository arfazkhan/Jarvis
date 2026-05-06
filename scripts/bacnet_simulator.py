#!/usr/bin/env python3
"""
BACnet/IP Simulator — Pure bacpypes3 async server for ARVIS testing.
"""

import asyncio
import logging
import random
from datetime import datetime

from bacpypes3.ipv4.app import BBMDApplication
from bacpypes3.basetypes import StatusFlags, Reliability
from bacpypes3.primitivedata import ObjectType, ObjectIdentifier
from bacpypes3.constructeddata import ArrayOf
from bacpypes3.object import AnalogInputObject, BinaryInputObject, MultiStateInputObject, DeviceObject

logging.basicConfig(level=logging.INFO, format='%(asctime)s [BACnetSim] %(message)s')
logger = logging.getLogger("bacnet.sim")

DEVICE_ID = 260001
LOCAL_ADDRESS = "172.20.19.153"
BACNET_PORT = 47808

state = {
    "ch1_chwst": 7.0, "ch1_chwrt": 12.0, "ch1_kw": 240.0, "ch1_load": 65.0, "ch1_status": 1,
    "ch2_chwst": 7.5, "ch2_chwrt": 12.5, "ch2_kw": 180.0, "ch2_load": 50.0, "ch2_status": 1,
    "ahu1_sat": 14.0, "ahu1_rat": 24.0, "ahu1_sf_spd": 75.0, "ahu1_oa_dmpr": 30.0,
    "ahu2_sat": 14.5, "ahu2_rat": 23.5, "ahu2_sf_spd": 70.0, "ahu2_oa_dmpr": 25.0,
    "meter_kw": 620.0,
}

object_definitions = [
    ("device", 0, {}),
    ("analogInput", 1, {"objectName": "CH1-CHWST", "description": "Chiller 1 Supply Water Temp", "units": "degreesCelsius"}),
    ("analogInput", 2, {"objectName": "CH1-CHWRT", "description": "Chiller 1 Return Water Temp", "units": "degreesCelsius"}),
    ("analogInput", 3, {"objectName": "CH1-KW", "description": "Chiller 1 Power", "units": "kilowatts"}),
    ("analogInput", 4, {"objectName": "CH1-LOAD", "description": "Chiller 1 Load %", "units": "percent"}),
    ("binaryInput", 1, {"objectName": "CH1-STATUS", "description": "Chiller 1 Running Status"}),
    ("analogInput", 11, {"objectName": "CH2-CHWST", "description": "Chiller 2 Supply Water Temp", "units": "degreesCelsius"}),
    ("analogInput", 12, {"objectName": "CH2-CHWRT", "description": "Chiller 2 Return Water Temp", "units": "degreesCelsius"}),
    ("analogInput", 13, {"objectName": "CH2-KW", "description": "Chiller 2 Power", "units": "kilowatts"}),
    ("analogInput", 14, {"objectName": "CH2-LOAD", "description": "Chiller 2 Load %", "units": "percent"}),
    ("binaryInput", 2, {"objectName": "CH2-STATUS", "description": "Chiller 2 Running Status"}),
    ("analogInput", 21, {"objectName": "AHU1-SAT", "description": "AHU 1 Supply Air Temp", "units": "degreesCelsius"}),
    ("analogInput", 22, {"objectName": "AHU1-RAT", "description": "AHU 1 Return Air Temp", "units": "degreesCelsius"}),
    ("analogInput", 23, {"objectName": "AHU1-SF-SPD", "description": "AHU 1 Supply Fan Speed", "units": "percent"}),
    ("analogInput", 24, {"objectName": "AHU1-OA-DMPR", "description": "AHU 1 OA Damper Position", "units": "percent"}),
    ("analogInput", 31, {"objectName": "AHU2-SAT", "description": "AHU 2 Supply Air Temp", "units": "degreesCelsius"}),
    ("analogInput", 32, {"objectName": "AHU2-RAT", "description": "AHU 2 Return Air Temp", "units": "degreesCelsius"}),
    ("analogInput", 33, {"objectName": "AHU2-SF-SPD", "description": "AHU 2 Supply Fan Speed", "units": "percent"}),
    ("analogInput", 34, {"objectName": "AHU2-OA-DMPR", "description": "AHU 2 OA Damper Position", "units": "percent"}),
    ("analogInput", 41, {"objectName": "METER-KW", "description": "Building Power", "units": "kilowatts"}),
]

object_state_map = {
    1: lambda: state["ch1_chwst"], 2: lambda: state["ch1_chwrt"],
    3: lambda: state["ch1_kw"], 4: lambda: state["ch1_load"],
    11: lambda: state["ch2_chwst"], 12: lambda: state["ch2_chwrt"],
    13: lambda: state["ch2_kw"], 14: lambda: state["ch2_load"],
    21: lambda: state["ahu1_sat"], 22: lambda: state["ahu1_rat"],
    23: lambda: state["ahu1_sf_spd"], 24: lambda: state["ahu1_oa_dmpr"],
    31: lambda: state["ahu2_sat"], 32: lambda: state["ahu2_rat"],
    33: lambda: state["ahu2_sf_spd"], 34: lambda: state["ahu2_oa_dmpr"],
    41: lambda: state["meter_kw"],
}

obj_type_map = {
    "analogInput": AnalogInputObject,
    "binaryInput": BinaryInputObject,
    "multiStateInput": MultiStateInputObject,
}


class BACnetSimulator(BBMDApplication):

    def __init__(self, device_obj, bind_address):
        super().__init__(device_obj, local_address=bind_address)
        self.objectList = ArrayOf(ObjectIdentifier)([])
        self._setup_objects()
        logger.info(f"Device {DEVICE_ID} on {bind_address}")

    def _setup_objects(self):
        for obj_type, obj_inst, kwargs in object_definitions:
            if obj_type == "device":
                continue
            cls = obj_type_map.get(obj_type)
            if cls:
                obj = cls(
                    objectIdentifier=(obj_type, obj_inst),
                    presentValue=0.0,
                    statusFlags=StatusFlags(founder=False, offline=False, fault=False, outOfOverride=False),
                    reliability=Reliability(noFaultDetected=True),
                    outOfService=False,
                    **kwargs,
                )
                self.objectList.append(obj)
        device_obj = DeviceObject(
            objectIdentifier=("device", DEVICE_ID),
            objectName="ARVIS-SIM-CHiller",
            modelName="ARVIS BMS Simulator v1.0",
            vendorName="ARVIS",
            vendorIdentifier=15,
            firmwareRevision="1.0.0",
            applicationSoftwareVersion="1.0.0",
            protocolVersion=1,
            protocolRevision=22,
            maxApduLengthAccepted=1476,
            segmentationSupported="segmented-both",
        )
        self.objectList.insert(0, device_obj)

    async def update_present_values(self):
        state["ch1_chwst"] = max(5.5, min(9.0, state["ch1_chwst"] + random.uniform(-0.3, 0.3)))
        state["ch1_chwrt"] = max(10.0, min(15.0, state["ch1_chwrt"] + random.uniform(-0.2, 0.2)))
        state["ch1_kw"] = max(120, min(400, state["ch1_kw"] + random.uniform(-8.0, 8.0)))
        state["ch1_load"] = max(20, min(100, state["ch1_load"] + random.uniform(-2.0, 2.0)))
        state["ch2_chwst"] = max(5.5, min(9.0, state["ch2_chwst"] + random.uniform(-0.3, 0.3)))
        state["ch2_chwrt"] = max(10.0, min(15.0, state["ch2_chwrt"] + random.uniform(-0.2, 0.2)))
        state["ch2_kw"] = max(80, min(350, state["ch2_kw"] + random.uniform(-6.0, 6.0)))
        state["ch2_load"] = max(20, min(100, state["ch2_load"] + random.uniform(-2.0, 2.0)))
        state["ahu1_sat"] = max(12.0, min(18.0, state["ahu1_sat"] + random.uniform(-0.3, 0.3)))
        state["ahu1_rat"] = max(20.0, min(28.0, state["ahu1_rat"] + random.uniform(-0.2, 0.2)))
        state["ahu1_sf_spd"] = max(30.0, min(100.0, state["ahu1_sf_spd"] + random.uniform(-2.0, 2.0)))
        state["ahu1_oa_dmpr"] = max(10.0, min(80.0, state["ahu1_oa_dmpr"] + random.uniform(-1.0, 1.0)))
        state["ahu2_sat"] = max(12.0, min(18.0, state["ahu2_sat"] + random.uniform(-0.3, 0.3)))
        state["ahu2_rat"] = max(20.0, min(28.0, state["ahu2_rat"] + random.uniform(-0.2, 0.2)))
        state["ahu2_sf_spd"] = max(30.0, min(100.0, state["ahu2_sf_spd"] + random.uniform(-2.0, 2.0)))
        state["ahu2_oa_dmpr"] = max(10.0, min(80.0, state["ahu2_oa_dmpr"] + random.uniform(-1.0, 1.0)))
        state["meter_kw"] = max(200.0, min(900.0, state["meter_kw"] + random.uniform(-15.0, 15.0)))

        for obj in self.objectList:
            if hasattr(obj, "presentValue") and obj.objectIdentifier[0] != "device":
                inst = obj.objectIdentifier[1]
                if inst in object_state_map:
                    obj.presentValue = object_state_map[inst]()


async def main():
    device_obj = DeviceObject(
        objectIdentifier=("device", DEVICE_ID),
        objectName="ARVIS-SIM-CHiller",
        modelName="ARVIS BMS Simulator v1.0",
        vendorName="ARVIS",
        vendorIdentifier=15,
        firmwareRevision="1.0.0",
        applicationSoftwareVersion="1.0.0",
    )
    app = BACnetSimulator(device_obj, f"{LOCAL_ADDRESS}:{BACNET_PORT}")

    tick = 0
    while True:
        await asyncio.sleep(5)
        tick += 5
        await app.update_present_values()
        logger.info(
            f"[{tick}s] CH1={state['ch1_chwst']:.1f}°C/{state['ch1_kw']:.0f}kW "
            f"AHU1={state['ahu1_sat']:.1f}°C METER={state['meter_kw']:.0f}kW"
        )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown.")