# -*- coding: utf-8 -*-

from battery import Battery, Cell
from utils import logger
import utils
import minimalmodbus
import serial
import threading
from typing import Dict, List, Tuple, Any
from semantic_version import Version
from enum import Enum
import functools
import time
from datetime import datetime, timedelta

# Define global variables
mbdevs: Dict[int, minimalmodbus.Instrument] = {}
port_locks: Dict[str, Any] = {}
address_locks: Dict[str, Any] = {}

class iRockFunctionType(Enum):
    SETTING = 1
    STATUS = 2
    
MODBUS_REGISTERS = [
    {
        "version": Version("1.0.0"),
        "register":
            {
                "manufacturer_id": {"name": "Manufacturer ID", "address": 0, "length": 1, "function": iRockFunctionType.SETTING, "type": int},
                "modbus_version": {"name": "Modbus Version", "address": 1, "length": 8, "function": iRockFunctionType.SETTING, "type": Version},
                "hardware_name": {"name": "Hardware Name", "address": 9, "length": 8, "function": iRockFunctionType.SETTING, "type": str},
                "hardware_version": {"name": "Hardware Version", "address": 17, "length": 4, "function": iRockFunctionType.SETTING, "type": Version},
                "serial_number": {"name": "Serial Number", "address": 21, "length": 6, "function": iRockFunctionType.SETTING, "type": str},
                "sw_version": {"name": "Software Version", "address": 27, "length": 8, "function": iRockFunctionType.SETTING, "type": Version},
                "number_of_cells": {"name": "Number of Cells", "address": 35, "length": 1, "function": iRockFunctionType.SETTING, "type": int},
                "capacity": {"name": "Capacity", "address": 36, "length": 2, "function": iRockFunctionType.SETTING, "type": float},
                "battery_voltage": {"name": "Battery Voltage", "address": 38, "length": 2, "function": iRockFunctionType.STATUS, "type": float},
                "battery_current": {"name": "Battery Current", "address": 40, "length": 2, "function": iRockFunctionType.STATUS, "type": float},
                "battery_soc": {"name": "Battery State of Charge", "address": 42, "length": 2, "function": iRockFunctionType.STATUS, "type": float},
                "remaining_capacity": {"name": "Remaining Capacity", "address": 44, "length": 2, "function": iRockFunctionType.STATUS, "type": float},
                "max_charge_current": {"name": "Max Charge Current", "address": 46, "length": 2, "function": iRockFunctionType.STATUS, "type": float},
                "max_discharge_current": {"name": "Max Discharge Current", "address": 48, "length": 2, "function": iRockFunctionType.STATUS, "type": float},
                "max_cell_voltage": {"name": "Max Cell Voltage", "address": 50, "length": 2, "function": iRockFunctionType.STATUS, "type": float},
                "min_cell_voltage": {"name": "Min Cell Voltage", "address": 52, "length": 2, "function": iRockFunctionType.STATUS, "type": float},
                "temperature_sensor_1": {"name": "Temperature Sensor 1", "address": 54, "length": 2, "function": iRockFunctionType.STATUS, "type": float},
                "temperature_sensor_2": {"name": "Temperature Sensor 2", "address": 56, "length": 2, "function": iRockFunctionType.STATUS, "type": float},
                "temperature_sensor_3": {"name": "Temperature Sensor 3", "address": 58, "length": 2, "function": iRockFunctionType.STATUS, "type": float},
                "temperature_sensor_4": {"name": "Temperature Sensor 4", "address": 60, "length": 2, "function": iRockFunctionType.STATUS, "type": float},
                "mosfet_temperature": {"name": "MOSFET Temperature", "address": 62, "length": 2, "function": iRockFunctionType.STATUS, "type": float},
            }
    }
]

MODBUS_VERSIONS: List[Version] = [register["version"] for register in MODBUS_REGISTERS]

HARDWARE_FUNCTIONS = {
    "iRock": ["manufacturer_id", "modbus_version", "hardware_name"],
    "iRock 424": ["manufacturer_id", "modbus_version", "hardware_name", "hardware_version", "serial_number", "sw_version", "number_of_cells", "capacity", "battery_voltage", "battery_soc", "max_charge_current", "max_discharge_current", "max_cell_voltage", "min_cell_voltage"]
}

def timed_lru_cache(days: float = 0, seconds: float = 0, microseconds: float = 0, milliseconds: float = 0, minutes: float = 0, hours: float = 0, weeks: float = 0, maxsize: int = 128):
    """
    Decorator that applies an LRU cache with a timed expiration to a function.
    """
    def wrapper(func):
        func = functools.lru_cache(maxsize=maxsize)(func)
        func.lifetime = timedelta(days=days, seconds=seconds, microseconds=microseconds, milliseconds=milliseconds, minutes=minutes, hours=hours, weeks=weeks)
        func.expiration = datetime.now() - func.lifetime

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
    def __init__(self, port, baud, address):
        """
        Initialize the iRock battery with port, baud, and address.
        """
        super(iRock, self).__init__(port, baud, address)
        self.address = address
        self.type = self.BATTERYTYPE
        self.serial_number: str = None
        self.hardware_name: str = None

    BATTERYTYPE = "iRock"
    
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
        found = False
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
            test = True
            test = test and self.get_field("hardware_name")
            if self.hardware_name is not None:
                self.type = self.hardware_name
            test = test and self.get_field("hardware_version")
            logger.debug(f"Found iRock of type \"{self.hardware_name} {self.hardware_version}\" on port {self.port} ({self.address})")
            if test:
                found = True
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
        mbdev = mbdevs[int.from_bytes(self.address, byteorder="big")]
        modbus_version = self.get_modbus_version(self.address)
        with port_locks[self.port]:
            with address_locks[self.address]:
                try:
                    if modbus_version == Version("1.0.0"):
                        serial_number = mbdev.read_string(21, 6).strip('\x00')
                        self.serial_number = serial_number
                        return serial_number
                    else:
                        logger.error(f"iRock Modbus Version ({modbus_version}) in get_settings not supported")
                except Exception as e:
                    logger.error(f"Can't get iRock settings: {e}")
        return self.serial_number

    def get_settings(self) -> bool:
        """
        Retrieve settings for the iRock battery.
        """
        mbdev = mbdevs[int.from_bytes(self.address, byteorder="big")]
        modbus_version = self.get_modbus_version(self.address)
        with port_locks[self.port]:
            with address_locks[self.address]:
                try:
                    if modbus_version == Version("1.0.0"):
                        self.cell_count = mbdev.read_register(35)
                        self.capacity = mbdev.read_float(36, byteorder=3)
                    else:
                        logger.error(f"iRock Modbus Version ({modbus_version}) in get_settings not supported")
                        return False
                    logger.debug(f"iRock Cell Count is {self.cell_count}")
                    logger.debug(f"iRock Capacity is {self.capacity}")
                except Exception as e:
                    logger.warning(f"Can't get iRock settings: {e}")
                    return False

        with port_locks[self.port]:
            with address_locks[self.address]:
                try:
                    if modbus_version == Version("1.0.0"):
                        self.max_battery_charge_current = mbdev.read_float(46, byteorder=3)
                        self.max_battery_discharge_current = mbdev.read_float(48, byteorder=3)
                        self.hardware_version = mbdev.read_string(17, 4).strip('\x00')
                        self.hardware_name = mbdev.read_string(9, 8).strip('\x00')
                        self.serial_number = mbdev.read_string(21, 6).strip('\x00')
                        self.max_battery_voltage = utils.MAX_CELL_VOLTAGE * self.cell_count
                        self.min_battery_voltage = utils.MIN_CELL_VOLTAGE * self.cell_count
                    else:
                        logger.error(f"iRock Modbus Version ({modbus_version}) in get_settings not supported")
                        return False
                    logger.debug(f"iRock Maximal Battery Charge Current is {self.max_battery_charge_current}")
                    logger.debug(f"iRock Maximal Battery Discharge Current is {self.max_battery_discharge_current}")
                    logger.debug(f"iRock Hardware Version is {self.hardware_version}")
                    logger.debug(f"iRock Hardware Name is {self.hardware_name}")
                    logger.debug(f"iRock Serial Number is {self.serial_number}")
                    logger.debug(f"iRock Maximal Battery Voltage is {self.max_battery_voltage}")
                    logger.debug(f"iRock Minimal Battery Voltage is {self.min_battery_voltage}")
                except Exception as e:
                    logger.error(f"Can't get iRock settings: {e}")
                    return False

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
        mbdev = mbdevs[int.from_bytes(self.address, byteorder="big")]
        modbus_version = self.get_modbus_version(self.address)
        with port_locks[self.port]:
            with address_locks[self.address]:
                try:
                    if modbus_version == Version("1.0.0"):
                        self.voltage = mbdev.read_float(38, byteorder=3)
                        self.current = mbdev.read_float(40, byteorder=3)
                        self.soc = mbdev.read_float(42, byteorder=3)
                        self.temp_1 = self.to_temp(1, mbdev.read_float(54, byteorder=3))
                        self.temp_2 = self.to_temp(2, mbdev.read_float(56, byteorder=3))
                        self.temp_3 = self.to_temp(3, mbdev.read_float(58, byteorder=3))
                        self.temp_4 = self.to_temp(4, mbdev.read_float(60, byteorder=3))
                        self.charge_fet = True
                        self.discharge_fet = True
                    else:
                        logger.error(f"iRock Modbus Version ({modbus_version}) in get_settings not supported")
                        return False
                except Exception as e:
                    logger.error(f"Can't get iRock settings: {e}")
                    return False
        return True

    def read_cell_data(self) -> bool:
        """
        Read cell data from the iRock battery.
        """
        mbdev = mbdevs[int.from_bytes(self.address, byteorder="big")]
        modbus_version = self.get_modbus_version(self.address)
        with port_locks[self.port]:
            with address_locks[self.address]:
                try:
                    for c in range(self.cell_count):
                        if modbus_version == Version("1.0.0"):
                            self.cells[c].voltage = mbdev.read_float(64 + c * 4, byteorder=3)
                            self.cells[c].balance = mbdev.read_register(66 + c * 4)
                        else:
                            logger.error(f"iRock Modbus Version ({modbus_version}) in read_cell_data not supported")
                            return False
                except Exception as e:
                    logger.error(f"Can't get iRock Cell Data: {e}")
                    return False
        return True
    
    @timed_lru_cache(seconds=60)
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
                    logger.debug(f"iRock ModBus Version is {str(modbus_version)}")
                    return modbus_version
        except Exception as e:
            logger.warning(f"Can't get iRock Modbus Version: {e}")
            return None
                
    @timed_lru_cache(seconds=1)
    def get_field(self, name: str) -> bool:
        """
        Get a specific field for the iRock battery.
        """
        mbdev = mbdevs[int.from_bytes(self.address, byteorder="big")]
        modbusVersion: Version = self.get_modbus_version(self.address)
        
        for modbusRegister in MODBUS_REGISTERS:
            if modbusRegister['version'].major == modbusVersion.major and modbusRegister['version'].minor == modbusVersion.minor:
                for fieldname, fielddata in modbusRegister['register'].items():
                    if fieldname == name:
                        supported_hardware_functions = list(set(HARDWARE_FUNCTIONS.get(self.type) + HARDWARE_FUNCTIONS.get("iRock")))
                        if supported_hardware_functions is None:
                            logger.warning(f"iRock Hardware Type \"{self.type}\" not supported")
                            return False
                        if name in supported_hardware_functions:
                            with port_locks[self.port]:
                                with address_locks[self.address]:
                                    try:
                                        logger.debug(f"iRock field {name} to be updated")
                                        if fielddata['type'] == str:
                                            result = mbdev.read_string(fielddata["address"], fielddata["length"]).strip('\x00')
                                        elif fielddata['type'] == int:
                                            result = mbdev.read_register(fielddata["address"])
                                        elif fielddata['type'] == float:
                                            result = mbdev.read_float(fielddata["address"], number_of_registers=fielddata["length"], byteorder=3)
                                        elif fielddata['type'] == Version:
                                            result = Version.coerce(str(mbdev.read_string(fielddata["address"], fielddata["length"]).strip('\x00')))
                                        else:
                                            logger.warning(f"iRock field type for field {name} not supported")
                                            return False
                                        setattr(self, name, result)
                                        logger.info(f"iRock field {name}: {result}")
                                        return True
                                    except Exception as e:
                                        logger.warning(f"Can't get iRock field {name}: {e}")
                        else:
                            logger.warning(f"iRock field {name} not supported for {self.type}")
                logger.warning(f"iRock field {name} not found")
        logger.warning(f"ModBus Version {modbusVersion} not supported")
        return False
