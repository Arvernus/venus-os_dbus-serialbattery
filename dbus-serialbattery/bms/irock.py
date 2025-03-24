# -*- coding: utf-8 -*-

from battery import Battery, Cell
from utils import logger
import utils
import ext.minimalmodbus as minimalmodbus
import serial
import threading
from typing import Dict, List, Any, Union
from semantic_version import Version
from enum import Enum
import functools
import time
from datetime import datetime, timedelta

# ModBus Value-Types
class BaseType(Enum):
    INT8 = "int8"
    UINT8 = "uint8"
    CHAR = "char"
    INT16 = "int16"
    UINT16 = "uint16"
    INT32 = "int32"
    UINT32 = "uint32"
    INT64 = "int64"
    UINT64 = "uint64"
    FLOAT32 = "float32"
    FLOAT64 = "float64"
    BOOL = "bool"

# Define global variables
mbdevs: Dict[int, minimalmodbus.Instrument] = {}
port_locks: Dict[str, Any] = {}
address_locks: Dict[str, Any] = {}

# logger.setLevel(10)

IROCK_TO_LOCAL_FIELD_NAMES: Dict[str, str] = {
    "Manufacturer_ID": "manufacturer_id",
    "Modbus_Version": "modbus_version",
    "Hardware_Name": "hardware_name",
    "Hardware_Version": "hardware_version",
    "Serial_Number": "serial_number",
    "SW_Version": "sw_version",
    "Number_of_Cells": "cell_count",
    "Capacity": "capacity",
    "Battery_Voltage": "voltage",
    "Battery_Current": "current",
    "Battery_SOC": "soc",
    "Remaining_Capacity": "remaining_capacity",
    "Max_Charge_Current": "max_battery_charge_current",
    "Max_Discharge_Current": "max_battery_discharge_current",
    "Max_Cell_Voltage": "max_battery_voltage_bms",
    "Min_Cell_Voltage": "min_battery_voltage_bms",
    "Temperature_Sensor_1": "temp1",
    "Temperature_Sensor_2": "temp2",
    "Temperature_Sensor_3": "temp3",
    "Temperature_Sensor_4": "temp4",
    "MOSFET_Temperature": "temp_mos",
    "Feedback_Shunt_Current": "feedback_shunt_current",
    "Charge_FET": "charge_fet",
    "Discharge_FET": "discharge_fet",
    "Alarm": "alarm",
    "Warning": "warning",
    "Cell_Voltage": "voltage",
    "Cell_Balance_Status": "balance",
    # Not yet found in the iRock Modbus register documentation (wild guess)
    "Production": "production",
    "Custom_Field": "custom_field",
    "SOH": "soh",
    "Balance_FET": "balance_fet"
}

IROCK_MODBUS_REGISTERS = [
    {'version': Version('2.0.0'), 'register': {'Manufacturer_ID': {'name': 'Manufacturer ID', 'address': 0, 'array_size': 1, 'type': 'uint16', 'description': 'Unique identifier of the manufacturer.', 'unit': None, 'hardware_support_register': None}, 'Modbus_Version': {'name': 'Modbus Version', 'address': 1, 'array_size': 16, 'type': 'char', 'description': 'Modbus protocol version, as a string in semantic versioning format. This field may not change between versions of the protocol.', 'unit': None, 'hardware_support_register': None}, 'Hardware_Name': {'name': 'Hardware Name', 'address': 9, 'array_size': 16, 'type': 'char', 'description': 'Name of the iRock hardware. Options include: `iRock 200`, `iRock 300`, `iRock 400`, `iRock 212` or `iRock 424`.', 'unit': None, 'hardware_support_register': None}, 'Hardware_Version': {'name': 'Hardware Version', 'address': 17, 'array_size': 8, 'type': 'char', 'description': 'Version identifier of the hardware, as a string in float format.', 'unit': None, 'hardware_support_register': None}, 'Serial_Number': {'name': 'Serial Number', 'address': 21, 'array_size': 12, 'type': 'char', 'description': 'Unique serial number of the iRock control board.', 'unit': None, 'hardware_support_register': None}, 'SW_Version': {'name': 'Software Version', 'address': 27, 'array_size': 16, 'type': 'char', 'description': 'Software version currently installed, as a string in semantic versioning format.', 'unit': None, 'hardware_support_register': None}, 'Number_of_Cells': {'name': 'Number of Cells', 'address': 35, 'array_size': 1, 'type': 'uint16', 'description': 'Number of battery cells in the system. May be any number between 2 and 24.', 'unit': None, 'hardware_support_register': None}, 'Battery_Voltage': {'name': 'Battery Voltage', 'address': 36, 'array_size': 1, 'type': 'float32', 'description': 'Total voltage of the battery pack.', 'unit': 'V', 'hardware_support_register': None}, 'Battery_Current': {'name': 'Battery Current', 'address': 38, 'array_size': 1, 'type': 'float32', 'description': 'Current flowing in or out of the battery. Positive values indicate charging, negative values indicate discharging.', 'unit': 'A', 'hardware_support_register': 0}, 'Battery_SOC': {'name': 'SOC', 'address': 40, 'array_size': 1, 'type': 'float32', 'description': 'State of Charge (SOC) of the battery.', 'unit': '%', 'hardware_support_register': 1}, 'Capacity': {'name': 'Capacity', 'address': 42, 'array_size': 1, 'type': 'float32', 'description': 'Total capacity of the battery pack.', 'unit': 'Ah', 'hardware_support_register': None}, 'Remaining_Capacity': {'name': 'Remaining Capacity', 'address': 44, 'array_size': 1, 'type': 'float32', 'description': 'Remaining available capacity in the battery pack.', 'unit': 'Ah', 'hardware_support_register': 2}, 'Max_Charge_Current': {'name': 'Max Charge Current', 'address': 46, 'array_size': 1, 'type': 'float32', 'description': 'Maximum current the battery can accept.', 'unit': 'A', 'hardware_support_register': None}, 'Max_Discharge_Current': {'name': 'Max Discharge Current', 'address': 48, 'array_size': 1, 'type': 'float32', 'description': 'Maximum current the battery can deliver.', 'unit': 'A', 'hardware_support_register': None}, 'Max_Cell_Voltage': {'name': 'Max Cell Voltage', 'address': 50, 'array_size': 1, 'type': 'float32', 'description': 'Maximum voltage recorded for any single cell.', 'unit': 'V', 'hardware_support_register': None}, 'Min_Cell_Voltage': {'name': 'Min Cell Voltage', 'address': 52, 'array_size': 1, 'type': 'float32', 'description': 'Minimum voltage recorded for any single cell.', 'unit': 'V', 'hardware_support_register': None}, 'Temperature_Sensor_1': {'name': 'Temperature Sensor 1', 'address': 54, 'array_size': 1, 'type': 'float32', 'description': 'Temperature reading from sensor 1.', 'unit': '°C', 'hardware_support_register': 3}, 'Temperature_Sensor_2': {'name': 'Temperature Sensor 2', 'address': 56, 'array_size': 1, 'type': 'float32', 'description': 'Temperature reading from sensor 2.', 'unit': '°C', 'hardware_support_register': 4}, 'Temperature_Sensor_3': {'name': 'Temperature Sensor 3', 'address': 58, 'array_size': 1, 'type': 'float32', 'description': 'Temperature reading from sensor 3.', 'unit': '°C', 'hardware_support_register': 5}, 'Temperature_Sensor_4': {'name': 'Temperature Sensor 4', 'address': 60, 'array_size': 1, 'type': 'float32', 'description': 'Temperature reading from sensor 4.', 'unit': '°C', 'hardware_support_register': 6}, 'MOSFET_Temperature': {'name': 'MOSFET Temperature', 'address': 62, 'array_size': 1, 'type': 'float32', 'description': 'MOSFET temperature sensor reading.', 'unit': '°C', 'hardware_support_register': 7}, 'Feedback_Shunt_Current': {'name': 'Feedback Shunt Current', 'address': 64, 'array_size': 1, 'type': 'float32', 'description': 'Current flowing through the feedback shunt. The feedback shunt messures the current of all ballancers in sum.', 'unit': 'A', 'hardware_support_register': 8}, 'Charge_FET': {'name': 'Charge FET', 'address': 66, 'array_size': 1, 'type': 'bool', 'description': 'Boolean indicating if the charge FET is active. `true` indicates active, `false` indicates inactive.', 'unit': None, 'hardware_support_register': None}, 'Discharge_FET': {'name': 'Discharge FET', 'address': 67, 'array_size': 1, 'type': 'bool', 'description': 'Boolean indicating if the discharge FET is active. `true` indicates active, `false` indicates inactive.', 'unit': None, 'hardware_support_register': None}, 'Low_Voltage_Alarm': {'name': 'Low Voltage Alarm', 'address': 68, 'array_size': 1, 'type': 'uint8', 'description': 'Alarm Status for low battery voltage. No Alarm may be `0`, Warnings may be `1` and Alarms may be `2`.', 'unit': None, 'hardware_support_register': None}, 'High_Voltage_Alarm': {'name': 'High Voltage Alarm', 'address': 69, 'array_size': 1, 'type': 'uint8', 'description': 'Alarm Status for high battery voltage. No Alarm may be `0`, Warnings may be `1` and Alarms may be `2`.', 'unit': None, 'hardware_support_register': None}, 'Low_Cell_Voltage_Alarm': {'name': 'Low Cell Voltage Alarm', 'address': 70, 'array_size': 1, 'type': 'uint8', 'description': 'Alarm Status for low cell voltage. No Alarm may be `0`, Warnings may be `1` and Alarms may be `2`.', 'unit': None, 'hardware_support_register': None}, 'High_Cell_Voltage_Alarm': {'name': 'High Cell Voltage Alarm', 'address': 71, 'array_size': 1, 'type': 'uint8', 'description': 'Alarm Status for high cell voltage. No Alarm may be `0`, Warnings may be `1` and Alarms may be `2`.', 'unit': None, 'hardware_support_register': None}, 'Low_SOC_Alarm': {'name': 'Low SOC Alarm', 'address': 72, 'array_size': 1, 'type': 'uint8', 'description': 'Alarm Status for low SOC. No Alarm may be `0`, Warnings may be `1` and Alarms may be `2`.', 'unit': None, 'hardware_support_register': None}, 'High_Charge_Current_Alarm': {'name': 'High Charge Current Alarm', 'address': 73, 'array_size': 1, 'type': 'uint8', 'description': 'Alarm Status for high charge current. No Alarm may be `0`, Warnings may be `1` and Alarms may be `2`.', 'unit': None, 'hardware_support_register': None}, 'High_Discharge_Current_Alarm': {'name': 'High Discharge Current Alarm', 'address': 74, 'array_size': 1, 'type': 'uint8', 'description': 'Alarm Status for high discharge current. No Alarm may be `0`, Warnings may be `1` and Alarms may be `2`.', 'unit': None, 'hardware_support_register': None}, 'Temperature_Alarm': {'name': 'Temperature Alarm', 'address': 75, 'array_size': 1, 'type': 'uint8', 'description': 'Alarm Status for high temperature. No Alarm may be `0`, Warnings may be `1` and Alarms may be `2`.', 'unit': None, 'hardware_support_register': None}}},
    {'version': Version('1.0.0'), 'register': {'Manufacturer_ID': {'name': 'Manufacturer ID', 'address': 0, 'array_size': 1, 'type': 'uint16', 'description': 'Unique identifier of the manufacturer.', 'unit': None, 'hardware_support_register': None}, 'Modbus_Version': {'name': 'Modbus Version', 'address': 1, 'array_size': 16, 'type': 'char', 'description': 'Modbus protocol version, as a string in semantic versioning format. This field may not change between versions of the protocol.', 'unit': None, 'hardware_support_register': None}, 'Hardware_Name': {'name': 'Hardware Name', 'address': 9, 'array_size': 16, 'type': 'char', 'description': 'Name of the iRock hardware. Options include: `iRock 200`, `iRock 300`, `iRock 400`, `iRock 212` or `iRock 424`.', 'unit': None, 'hardware_support_register': None}, 'Hardware_Version': {'name': 'Hardware Version', 'address': 17, 'array_size': 8, 'type': 'char', 'description': 'Version identifier of the hardware, as a string in float format.', 'unit': None, 'hardware_support_register': None}, 'Serial_Number': {'name': 'Serial Number', 'address': 21, 'array_size': 12, 'type': 'char', 'description': 'Unique serial number of the iRock control board.', 'unit': None, 'hardware_support_register': None}, 'SW_Version': {'name': 'Software Version', 'address': 27, 'array_size': 16, 'type': 'char', 'description': 'Software version currently installed, as a string in semantic versioning format.', 'unit': None, 'hardware_support_register': None}, 'Number_of_Cells': {'name': 'Number of Cells', 'address': 35, 'array_size': 1, 'type': 'uint16', 'description': 'Number of battery cells in the system. May be any number between 2 and 24.', 'unit': None, 'hardware_support_register': None}, 'Battery_Voltage': {'name': 'Battery Voltage', 'address': 36, 'array_size': 1, 'type': 'float32', 'description': 'Total voltage of the battery pack.', 'unit': 'V', 'hardware_support_register': None}, 'Battery_Current': {'name': 'Battery Current', 'address': 38, 'array_size': 1, 'type': 'float32', 'description': 'Current flowing in or out of the battery. Positive values indicate charging, negative values indicate discharging.', 'unit': 'A', 'hardware_support_register': None}, 'Battery_SOC': {'name': 'SOC', 'address': 40, 'array_size': 1, 'type': 'float32', 'description': 'State of Charge (SOC) of the battery.', 'unit': '%', 'hardware_support_register': None}, 'Capacity': {'name': 'Capacity', 'address': 42, 'array_size': 1, 'type': 'float32', 'description': 'Total capacity of the battery pack.', 'unit': 'Ah', 'hardware_support_register': None}, 'Remaining_Capacity': {'name': 'Remaining Capacity', 'address': 44, 'array_size': 1, 'type': 'float32', 'description': 'Remaining available capacity in the battery pack.', 'unit': 'Ah', 'hardware_support_register': None}, 'Max_Charge_Current': {'name': 'Max Charge Current', 'address': 46, 'array_size': 1, 'type': 'float32', 'description': 'Maximum current the battery can accept.', 'unit': 'A', 'hardware_support_register': None}, 'Max_Discharge_Current': {'name': 'Max Discharge Current', 'address': 48, 'array_size': 1, 'type': 'float32', 'description': 'Maximum current the battery can deliver.', 'unit': 'A', 'hardware_support_register': None}, 'Max_Cell_Voltage': {'name': 'Max Cell Voltage', 'address': 50, 'array_size': 1, 'type': 'float32', 'description': 'Maximum voltage recorded for any single cell.', 'unit': 'V', 'hardware_support_register': None}, 'Min_Cell_Voltage': {'name': 'Min Cell Voltage', 'address': 52, 'array_size': 1, 'type': 'float32', 'description': 'Minimum voltage recorded for any single cell.', 'unit': 'V', 'hardware_support_register': None}, 'Temperature_Sensor_1': {'name': 'Temperature Sensor 1', 'address': 54, 'array_size': 1, 'type': 'float32', 'description': 'Temperature reading from sensor 1.', 'unit': '°C', 'hardware_support_register': None}, 'Temperature_Sensor_2': {'name': 'Temperature Sensor 2', 'address': 56, 'array_size': 1, 'type': 'float32', 'description': 'Temperature reading from sensor 2.', 'unit': '°C', 'hardware_support_register': None}, 'Temperature_Sensor_3': {'name': 'Temperature Sensor 3', 'address': 58, 'array_size': 1, 'type': 'float32', 'description': 'Temperature reading from sensor 3.', 'unit': '°C', 'hardware_support_register': None}, 'Temperature_Sensor_4': {'name': 'Temperature Sensor 4', 'address': 60, 'array_size': 1, 'type': 'float32', 'description': 'Temperature reading from sensor 4.', 'unit': '°C', 'hardware_support_register': None}, 'MOSFET_Temperature': {'name': 'MOSFET Temperature', 'address': 62, 'array_size': 1, 'type': 'float32', 'description': 'MOSFET temperature sensor reading.', 'unit': '°C', 'hardware_support_register': None}}},
]

IROCK_MODBUS_CELL_REGISTERS = [
    {'version': Version('2.0.0'), 'offset': 76, 'length': 3, 'register': {'Cell_Voltage': {'name': 'Cell Voltage', 'offset': 0, 'array_size': 1, 'type': 'float32', 'description': 'Voltage of cell.', 'unit': 'V', 'hardware_support_register': None}, 'Cell_Balance_Status': {'name': 'Cell Balance Status', 'offset': 2, 'array_size': 1, 'type': 'bool', 'description': 'Boolean indicating if the cells balancer is active. `true` indicates active, `false` indicates inactive.', 'unit': None, 'hardware_support_register': None}}},
    {'version': Version('1.0.0'), 'offset': 64, 'length': 4, 'register': {'Cell_Voltage': {'name': 'Cell Voltage', 'offset': 0, 'array_size': 1, 'type': 'float32', 'description': 'Voltage of cell.', 'unit': 'V', 'hardware_support_register': None}, 'Cell_Balance_Status': {'name': 'Cell Balance Status', 'offset': 2, 'array_size': 1, 'type': 'bool', 'description': 'Boolean indicating if the cells balancer is active. `true` indicates active, `false` indicates inactive.', 'unit': None, 'hardware_support_register': None}, 'res': {'name': 'Reserved', 'offset': 3, 'array_size': 1, 'type': 'uint16', 'description': 'Reserved', 'unit': None, 'hardware_support_register': None}}},
]

def timed_lru_cache(days: float = 0, seconds: float = 0, microseconds: float = 0, milliseconds: float = 0, minutes: float = 0, hours: float = 0, weeks: float = 0, maxsize: int = 128):
    """
    Decorator that applies an LRU cache with a timed expiration to a function.
    """
    def wrapper(func):
        func = functools.lru_cache(maxsize=maxsize)(func)
        func.lifetime = timedelta(days=days, seconds=seconds, microseconds=microseconds, milliseconds=milliseconds, minutes=minutes, hours=hours, weeks=weeks)
        func.expiration = datetime.now() + func.lifetime

        @functools.wraps(func)
        def wrapped_func(*args, **kwargs):
            if datetime.now() >= func.expiration:
                func.cache_clear()
                func.expiration = datetime.now() + func.lifetime
            result = func(*args, **kwargs)
            if result is None:
                func.cache_clear()
            return result
        
        return wrapped_func
    return wrapper

class iRock(Battery):
    BATTERYTYPE = "iRock"

    def __init__(self, port, baud, address):
        """
        Initialize the iRock battery with port, baud, and address.
        """
        super(iRock, self).__init__(port, baud, address)
        self.poll_interval: int = 5000
        self.address = address
        self.type = self.BATTERYTYPE
        self.serial_number: str = None
        self.hardware_name: str = None
    
    def custom_name(self) -> str:
        """
        Return a custom name for the iRock battery.
        """
        name: str = f"{self.type} ({self.serial_number})"
        return name
    
    def test_connection(self) -> bool:
        """
        Test the connection to the iRock battery.
        """
        logger.debug("Testing on slave address " + str(self.address))
        found = True
        if self.port not in port_locks:
            port_locks[self.port] = threading.Lock()
        if self.address not in address_locks:
            address_locks[self.address] = threading.Lock()
        with port_locks[self.port]:
            with address_locks[self.address]:
                mbdev = minimalmodbus.Instrument(
                    self.port,
                    slaveaddress=int.from_bytes(self.address, byteorder="big"),
                    mode="rtu",
                    close_port_after_each_call=True,
                    debug=False,
                )
                mbdev.serial.parity = minimalmodbus.serial.PARITY_NONE
                mbdev.serial.stopbits = serial.STOPBITS_ONE
                mbdev.serial.baudrate = 9600
                mbdev.serial.timeout = 1
                mbdevs[int.from_bytes(self.address, byteorder="big")] = mbdev
        try:
            found = self.get_field("hardware_name", found)
            if self.hardware_name is not None:
                self.type = self.hardware_name
                self.custom_name()
            found = self.get_field("hardware_version", found)
            logger.debug(f"Found iRock of type \"{self.hardware_name} {self.hardware_version}\" on port {self.port} ({self.address})")
        except Exception as e:
            logger.info(f"Testing failed for iRock on port {self.port} ({self.address}): {e}")

        if not found:
            logger.error("iRock not found")

        return (
            found
            and self.get_settings()
            and self.refresh_data()
        )

    def unique_identifier(self) -> str:
        """
        Return a unique identifier for the iRock battery.
        """
        self.get_field("serial_number")
        return self.serial_number

    def get_settings(self) -> bool:
        """
        Retrieve settings for the iRock battery.
        """
        # Mandatory values to set
        answer: bool = True
        answer = self.get_field("cell_count", answer)
        answer = self.get_field("capacity", answer)
        if not answer:
            logger.error(f"Can't get iRock settings")
            return False
        # Optional values to set
        answer = self.get_field("max_battery_charge_current", answer)
        answer = self.get_field("max_battery_discharge_current", answer)
        answer = self.get_field("custom_field", answer)
        answer = self.get_field("max_battery_voltage_bms", answer)
        answer = self.get_field("min_battery_voltage_bms", answer)
        answer = self.get_field("production", answer)
        answer = self.get_field("hardware_version", answer)
        answer = self.get_field("hardware_name", answer)
        answer = self.get_field("serial_number", answer)
        # Create Cells
        if len(self.cells) == 0:
            for _ in range(self.cell_count):
                self.cells.append(Cell(False))
        return True

    def refresh_data(self) -> bool:
        """
        Refresh the data for the iRock battery.
        """
        result = self.read_status_data()
        result = result and self.read_cell_data()
        return result

    def read_status_data(self) -> bool:
        """
        Read status data from the iRock battery.
        """
        # Mandatory values to set
        answer: bool = True
        answer = self.get_field("voltage", answer)
        answer = self.get_field("current", answer)
        answer = self.get_field("soc", answer)
        answer = self.get_field("soh", answer)
        answer = self.get_field("temperature_1", answer)
        answer = self.get_field("charge_fet", answer)
        answer = self.get_field("discharge_fet", answer)
        if not answer:
            logger.error(f"Can't get iRock status")
            return False
        # Optional values to set
        answer = self.get_field("capacity_remain", answer)
        answer = self.get_field("temperature_2", answer)
        answer = self.get_field("temperature_3", answer)
        answer = self.get_field("temperature_4", answer)
        answer = self.get_field("temperature_mos", answer)
        answer = self.get_field("balance_fet", answer)
        answer = self.get_field("protection.high_voltage", answer)
        answer = self.get_field("protection.high_cell_voltage", answer)
        answer = self.get_field("protection.low_voltage", answer)
        answer = self.get_field("protection.low_cell_voltage", answer)
        answer = self.get_field("protection.low_soc", answer)
        answer = self.get_field("protection.high_charge_current", answer)
        answer = self.get_field("protection.high_discharge_current", answer)
        answer = self.get_field("protection.cell_imbalance", answer)
        answer = self.get_field("protection.internal_failure", answer)
        answer = self.get_field("protection.high_charge_temperature", answer)
        answer = self.get_field("protection.low_charge_temperature", answer)
        answer = self.get_field("protection.high_temperature", answer)
        answer = self.get_field("protection.low_temperature", answer)
        answer = self.get_field("protection.high_internal_temperature", answer)
        answer = self.get_field("protection.fuse_blown", answer)
        answer = self.get_field("history.deepest_discharge", answer)
        answer = self.get_field("history.last_discharge", answer)
        answer = self.get_field("history.average_discharge", answer)
        answer = self.get_field("history.charge_cycles", answer)
        answer = self.get_field("history.full_discharges", answer)
        answer = self.get_field("history.total_ah_drawn", answer)
        answer = self.get_field("history.minimum_voltage", answer)
        answer = self.get_field("history.maximum_voltage", answer)
        answer = self.get_field("history.minimum_cell_voltage", answer)
        answer = self.get_field("history.maximum_cell_voltage", answer)
        answer = self.get_field("history.timestamp_last_full_charge", answer)
        answer = self.get_field("history.low_voltage_alarms", answer)
        answer = self.get_field("history.high_voltage_alarms", answer)
        answer = self.get_field("history.minimum_temperature", answer)
        answer = self.get_field("history.maximum_temperature", answer)
        answer = self.get_field("history.discharged_energy", answer)
        answer = self.get_field("history.charged_energy", answer)
        return True

    def read_cell_data(self) -> bool:
        """
        Read cell data from the iRock battery.
        """
        # Mandatory values to set
        answer: bool = True
        for c in range(self.cell_count):
            answer = self.get_cell_field("voltage", c, answer)
        if not answer:
            logger.error(f"Can't get iRock cell data")
            return False
        # Optional values to set
        for c in range(self.cell_count):
            answer = self.get_cell_field("balance", c, answer)
        return True

    @timed_lru_cache(minutes=2)
    def get_modbus_version(self, address: str) -> Version:
        """
        Get the Modbus version for the iRock battery.
        """
        mbdev = mbdevs[int.from_bytes(address, byteorder="big")]
        try:
            with port_locks[self.port]:
                with address_locks[self.address]:
                    modbus_version = Version.coerce(str(mbdev.read_string(1, 8).strip('\x00')))
                    if modbus_version is None:
                        logger.error("Can't get iRock Modbus Version")
                        return None
                    elif modbus_version.major == 0:
                        logger.error("iRock ModBus Version 0.x.x not supported")
                        return None
                    logger.info(f"iRock ModBus Version is {str(modbus_version)}")
                    return modbus_version
        except Exception as e:
            logger.warning(f"Can't get iRock Modbus Version: {e}")
        return None

    @timed_lru_cache(minutes=2)
    def get_modbus_hw_support(self, address: int) -> bool:
        mbdev = mbdevs[int.from_bytes(self.address, byteorder="big")]
        with port_locks[self.port]:
            with address_locks[self.address]:
                try:
                    result = mbdev.read_bit(address, 1)
                    return result != 0
                except Exception as e:
                    logger.warning(f"Can't read iRock HW Support Coil: {e}")
        return False

    def get_modbus_value(self, address: int, type: str, size: int = 1):
        # TODO: Arrays are only supported for CHAR
        mbdev = mbdevs[int.from_bytes(self.address, byteorder="big")]
        type = BaseType(type)
        with port_locks[self.port]:
            with address_locks[self.address]:
                try:
                    result = None
                    if type == BaseType.CHAR:
                        result = mbdev.read_string(address, size/2)
                    elif type == BaseType.INT16:
                        result = mbdev.read_register(address, signed=True)
                    elif type == BaseType.UINT16:
                        result = mbdev.read_register(address)
                    elif type == BaseType.INT32:
                        result = mbdev.read_long(address, signed=True)
                    elif type == BaseType.UINT32:
                        result = mbdev.read_long(address)
                    elif type == BaseType.INT64:
                        result = mbdev.read_long(address, signed=True, number_of_registers=4)
                    elif type == BaseType.UINT64:
                        result = mbdev.read_long(address, number_of_registers=4)
                    elif type == BaseType.FLOAT32:
                        result = mbdev.read_float(address, number_of_registers=2, byteorder=minimalmodbus.BYTEORDER_LITTLE_SWAP)
                    elif type == BaseType.FLOAT64:
                        result = mbdev.read_float(address, number_of_registers=4, byteorder=minimalmodbus.BYTEORDER_LITTLE_SWAP)
                    elif type == BaseType.BOOL:
                        result = mbdev.read_register(address) != 0
                    if result is None:
                        logger.warning(f"iRock field type {type} not supported")
                    return result
                except Exception as e:
                    logger.warning(f"Can't get iRock type {type}: {e}")
        return None

    @timed_lru_cache(seconds=1)
    def get_field(self, name: str, andOperator: bool = True) -> bool:
        """
        Get a specific field from the iRock battery.
        """
        mbdev = mbdevs[int.from_bytes(self.address, byteorder="big")]
        modbusVersion: Version = self.get_modbus_version(self.address)        
        # Lookup Modbus Register Name for a Dbus Serial Battery Name
        for modbusRegisterTable in IROCK_MODBUS_REGISTERS:
            if modbusRegisterTable['version'].major == modbusVersion.major and modbusRegisterTable['version'].minor == modbusVersion.minor:
                for fieldname, fielddata in modbusRegisterTable['register'].items():
                    OrgName = IROCK_TO_LOCAL_FIELD_NAMES[fieldname]
                    if OrgName == name:
                        if fielddata['hardware_support_register'] is not None:
                            if not self.get_modbus_hw_support(fielddata['hardware_support_register']):
                                logger.warning(f"iRock Hardware Type \"{self.type}\" does not supported field {name}")
                                return False
                        value = self.get_modbus_value(fielddata['address'],fielddata['type'],fielddata.array_size)
                        NP = OrgName.split(".")
                        if len(NP) == 2:
                            setattr(self, NP[1], value)
                        else:
                            logger.warning(f"Invalid field name format: {OrgName}")
                        return andOperator
        logger.warning(f"iRock field {name} not found")
        return False

    @timed_lru_cache(seconds=1)
    def get_cell_field(self, name: str, cell: int, andOperator: bool = True) -> bool:
        """
        Get a specific cell field from the iRock battery.
        """
        mbdev = mbdevs[int.from_bytes(self.address, byteorder="big")]
        modbusVersion: Version = self.get_modbus_version(self.address)
        # Lookup Modbus Register Name for a Dbus Serial Battery Name
        for modbusRegisterTable in IROCK_MODBUS_CELL_REGISTERS:
            if modbusRegisterTable['version'].major == modbusVersion.major and modbusRegisterTable['version'].minor == modbusVersion.minor:
                for fieldname, fielddata in modbusRegisterTable['register'].items():
                    OrgName = IROCK_TO_LOCAL_FIELD_NAMES[fieldname]
                    if OrgName == name:
                        if fielddata['hardware_support_register'] is not None:
                            if not self.get_modbus_hw_support(fielddata['hardware_support_register']):
                                logger.warning(f"iRock Hardware Type \"{self.type}\" does not supported field {name}")
                                return False
                        adr = modbusRegisterTable.offset + (modbusRegisterTable.length * (cell - 1)) + fielddata.offset
                        value = self.get_modbus_value(adr,fielddata['type'],fielddata.array_size)
                        NP = OrgName.split(".")
                        if len(NP) == 2:
                            setattr(self.cell[cell], NP[1], value)
                        else:
                            logger.warning(f"Invalid field name format: {OrgName}")
                        return andOperator
        logger.warning(f"iRock field {name} not found")
        return False
