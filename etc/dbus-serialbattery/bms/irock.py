# -*- coding: utf-8 -*-

from battery import Battery, Cell
from utils import logger
import utils
import minimalmodbus
import serial
import threading
from typing import Dict, List, Any
from semantic_version import Version
from enum import Enum
import functools
import time
from datetime import datetime, timedelta

# Define global variables
mbdevs: Dict[int, minimalmodbus.Instrument] = {}
port_locks: Dict[str, Any] = {}
address_locks: Dict[str, Any] = {}

# logger.setLevel(10)

class iRockFunctionType(Enum):
    SETTING = 1
    STATUS = 2
    CELL = 3
    
IROCK_MODBUS_REGISTERS = [
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
                "cell_count": {"name": "Number of Cells", "address": 35, "length": 1, "function": iRockFunctionType.SETTING, "type": int},
                "capacity": {"name": "Capacity", "address": 36, "length": 2, "function": iRockFunctionType.SETTING, "type": float},
                "voltage": {"name": "Battery Voltage", "address": 38, "length": 2, "function": iRockFunctionType.STATUS, "type": float},
                "current": {"name": "Battery Current", "address": 40, "length": 2, "function": iRockFunctionType.STATUS, "type": float},
                "soc": {"name": "Battery State of Charge", "address": 42, "length": 2, "function": iRockFunctionType.STATUS, "type": float},
                "remaining_capacity": {"name": "Remaining Capacity", "address": 44, "length": 2, "function": iRockFunctionType.STATUS, "type": float},
                "max_battery_charge_current": {"name": "Max Charge Current", "address": 46, "length": 2, "function": iRockFunctionType.SETTING, "type": float},
                "max_battery_discharge_current": {"name": "Max Discharge Current", "address": 48, "length": 2, "function": iRockFunctionType.SETTING, "type": float},
                "max_battery_voltage": {"name": "Max Battery Voltage", "address": 50, "length": 2, "function": iRockFunctionType.STATUS, "type": float},
                "min_battery_voltage": {"name": "Min Battery Voltage", "address": 52, "length": 2, "function": iRockFunctionType.STATUS, "type": float},
                "temp1": {"name": "Temperature Sensor 1", "address": 54, "length": 2, "function": iRockFunctionType.STATUS, "type": float},
                "temp2": {"name": "Temperature Sensor 2", "address": 56, "length": 2, "function": iRockFunctionType.STATUS, "type": float},
                "temp3": {"name": "Temperature Sensor 3", "address": 58, "length": 2, "function": iRockFunctionType.STATUS, "type": float},
                "temp4": {"name": "Temperature Sensor 4", "address": 60, "length": 2, "function": iRockFunctionType.STATUS, "type": float},
                "temp_mos": {"name": "MOSFET Temperature", "address": 62, "length": 2, "function": iRockFunctionType.STATUS, "type": float},
            }
    }
]
IROCK_MODBUS_CELL_REGISTERS = [
    {
        "version": Version("1.0.0"),
        "offset": 64,
        "length": 4,
        "register":
            {
                "voltage": {"name": "Cell Voltage", "address": 0, "length": 2, "function": iRockFunctionType.CELL, "type": float},
                "balance": {"name": "Cell Balace Status", "address": 2, "length": 1, "function": iRockFunctionType.CELL, "type": bool},
            }
    }
]

IROCK_HARDWARE_FUNCTIONS = {
    "iRock": {
        "register": ["manufacturer_id", "modbus_version", "hardware_name"]},
    "iRock 424": {
        "register": ["manufacturer_id", "modbus_version", "hardware_name", "hardware_version", "serial_number", "sw_version", "cell_count", "capacity", "voltage", "soc", "max_battery_charge_current", "max_battery_discharge_current", "max_battery_voltage", "min_battery_voltage"],
        "cell_register": ["voltage", "balance"]},
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
        self.poll_interval: int = 5000
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
        answer: bool = True
        answer = self.get_field("cell_count", answer)
        answer = self.get_field("capacity", answer)
        if not answer:
            logger.error(f"Can't get iRock settings")
            return False
        
        answer = self.get_field("max_battery_charge_current", answer)
        answer = self.get_field("max_battery_discharge_current", answer)
        answer = self.get_field("hardware_version", answer)
        answer = self.get_field("hardware_name", answer)
        answer = self.get_field("serial_number", answer)
        answer = self.get_field("max_battery_voltage", answer)
        answer = self.get_field("min_battery_voltage", answer)

        if len(self.cells) == 0:
            for _ in range(self.cell_count):
                self.cells.append(Cell(False))

        return answer

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
        #TODO: temp_sensors setzen
        answer: bool = True
        answer = self.get_field("voltage", answer)
        answer = self.get_field("current", answer)
        answer = self.get_field("soc", answer)
        answer = self.get_field("temp1", answer)
        answer = self.get_field("temp2", answer)
        answer = self.get_field("temp3", answer)
        answer = self.get_field("temp4", answer)
        return answer

    def read_cell_data(self) -> bool:
        """
        Read cell data from the iRock battery.
        """
        answer: bool = True
        for c in range(self.cell_count):
            answer = self.get_field("voltage", answer, cell = c)
            answer = self.get_field("balance", answer, cell = c)
        return answer
    
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
                
    @timed_lru_cache(seconds=1)
    def get_field(self, name: str, andOperator: bool = True, cell: int = None) -> bool:
        """
        Get a specific field for the iRock battery.
        """
        mbdev = mbdevs[int.from_bytes(self.address, byteorder="big")]
        modbusVersion: Version = self.get_modbus_version(self.address)
        

        # Check if the cell is set
        if cell is None:
            # Iterate over each modbus registerlist
            for modbusRegister in IROCK_MODBUS_REGISTERS:
                # Check if the version of the modbus registerlist matches the modbus version of the battery
                if modbusRegister['version'].major == modbusVersion.major and modbusRegister['version'].minor == modbusVersion.minor:
                    # Iterate over each field in the modbus register
                    for fieldname, fielddata in modbusRegister['register'].items():
                        # Check if the field name matches the requested name
                        if fieldname == name:
                            # Get hardware functions for the iRock battery
                            default_hardware_functions = IROCK_HARDWARE_FUNCTIONS.get("iRock").get("register")
                            type_hardware_functions = IROCK_HARDWARE_FUNCTIONS.get(self.type).get("register")
                            supported_hardware_functions = list(set(type_hardware_functions + default_hardware_functions))
                            if supported_hardware_functions is None:
                                logger.warning(f"iRock Hardware Type \"{self.type}\" not supported")
                                return True
                            # Check if the requested field is in the supported hardware functions
                            if name in supported_hardware_functions:
                                with port_locks[self.port]:
                                    with address_locks[self.address]:
                                        try:
                                            logger.debug(f"iRock field {name} to be updated from address {fielddata['address']} with length {fielddata['length']} and datatype {fielddata['type']}")
                                            result = None
                                            if fielddata['type'] == str:
                                                result = mbdev.read_string(fielddata["address"], fielddata["length"]).strip('\x00')
                                            elif fielddata['type'] == int:
                                                result = mbdev.read_register(fielddata["address"])
                                            elif fielddata['type'] == float:
                                                result = mbdev.read_float(fielddata["address"], number_of_registers=fielddata["length"], byteorder=3)
                                            elif fielddata['type'] == Version:
                                                result = str(Version.coerce(str(mbdev.read_string(fielddata["address"], fielddata["length"]).strip('\x00'))))
                                            elif fielddata['type'] == bool:
                                                register = mbdev.read_register(fielddata["address"])
                                                result = register == 1
                                            else:
                                                logger.warning(f"iRock field type for field {name} not supported")
                                                return False
                                            if result is None:
                                                logger.warning(f"iRock field {name} not found")
                                                return False
                                            setattr(self, name, result)
                                            logger.info(f"iRock field {name}: {result}")
                                            return andOperator and True
                                        except Exception as e:
                                            logger.warning(f"Can't get iRock field {name}: {e}")
                            else:
                                logger.info(f"iRock field {name} not supported for {self.type}")
                                return True
                    logger.warning(f"iRock field {name} not found")
        else:
            # Iterate over each modbus registerlist
            for modbusCellRegister in IROCK_MODBUS_CELL_REGISTERS:
                # Check if the version of the modbus registerlist matches the modbus version of the battery
                if modbusCellRegister['version'].major == modbusVersion.major and modbusCellRegister['version'].minor == modbusVersion.minor:
                    cellOfset = modbusCellRegister.get("offset")
                    cellLength = modbusCellRegister.get("length")
                    # Iterate over each field in the modbus register
                    for fieldname, fielddata in modbusCellRegister['register'].items():
                        # Check if the field name matches the requested name
                        if fieldname == name:
                            # Get hardware functions for the iRock battery
                            supported_cell_hardware_functions = IROCK_HARDWARE_FUNCTIONS.get(self.type).get("cell_register")
                            if supported_cell_hardware_functions is None:
                                logger.warning(f"iRock Hardware Type \"{self.type}\" not supported")
                                return True
                            # Check if the requested field is in the supported hardware functions
                            if name in supported_cell_hardware_functions:
                                with port_locks[self.port]:
                                    with address_locks[self.address]:
                                        try:
                                            logger.debug(f"iRock cell field {name} to be updated from address {fielddata['address'] + cell * cellLength + cellOfset} with length {fielddata['length']} and datatype {fielddata['type']}")
                                            result = None
                                            if fielddata['type'] == float:
                                                result = mbdev.read_float(fielddata['address'] + cell * cellLength + cellOfset, number_of_registers=fielddata["length"], byteorder=3)
                                            elif fielddata['type'] == bool:
                                                register = mbdev.read_register(fielddata['address'] + cell * cellLength + cellOfset)
                                                result = register == 1
                                            else:
                                                logger.warning(f"iRock field type for field {name} not supported")
                                                return False
                                            if result is None:
                                                logger.warning(f"iRock field {name} not found")
                                                return False
                                            setattr(self.cells[cell], name, result)
                                            logger.info(f"iRock field {name}: {result}")
                                            return andOperator and True
                                        except Exception as e:
                                            logger.warning(f"Can't get iRock field {name}: {e}")
                            else:
                                logger.warning(f"iRock field {name} not supported for {self.type}")
                    logger.warning(f"iRock field {name} not found")
        logger.warning(f"ModBus Version {modbusVersion} not supported")
        return False