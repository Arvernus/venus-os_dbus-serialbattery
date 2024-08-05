# -*- coding: utf-8 -*-

from battery import Battery, Cell
from utils import logger
import utils
import minimalmodbus
import serial
import threading
from typing import Dict, List
from semantic_version import Version
from enum import Enum

mbdevs: Dict[int, minimalmodbus.Instrument] = {}
locks: Dict[int, any] = {}

class iRockFunctionType(Enum):
    SETTING = 1
    STATUS = 2
    
MODBUS_REGISTERS = [
    {
        "version": Version("1.0.0"),
        "register":
            {
                "manufacturer_id": {"name": "Manufacturer ID", "address": 0, "length": 1, "function": iRockFunctionType.SETTING, "type": int},
                "modbus_version": {"name": "Modbus Version", "address": 1, "length": 16, "function": iRockFunctionType.SETTING, "type": Version},
                "hardware_name": {"name": "Hardware Name", "address": 9, "length": 16, "function": iRockFunctionType.SETTING, "type": str},
                "type": {"name": "Hardware Name", "address": 9, "length": 16, "function": iRockFunctionType.SETTING, "type": str},
                "hardware_version": {"name": "Hardware Version", "address": 17, "length": 8, "function": iRockFunctionType.SETTING, "type": Version},
                "serial_number": {"name": "Serial Number", "address": 21, "length": 12, "function": iRockFunctionType.SETTING, "type": str},
                "sw_version": {"name": "Software Version", "address": 27, "length": 16, "function": iRockFunctionType.SETTING, "type": Version},
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

MODBUS_VERSIONS = [register["version"] for register in MODBUS_REGISTERS]

HARDWARE_FUNCTIONS = {
    "iRock 424": ["manufacturer_id", "modbus_version", "hardware_name", "hardware_version", "serial_number", "sw_version", "number_of_cells", "capacity", "battery_voltage", "battery_soc", "max_charge_current", "max_discharge_current", "max_cell_voltage", "min_cell_voltage"]
}

class iRock(Battery):
    def __init__(self, port, baud, address):
        super(iRock, self).__init__(port, baud, address)
        self.address = address
        self.type = self.BATTERYTYPE
        self.serial_number: str = None
        self.hardware_name: str = None

    BATTERYTYPE = "iRock"
    
    
    def custom_name(self) -> str:
        name: str = f"{self.type} ({self.serial_number})"
        return name
    
    def test_connection(self):
        logger.debug("Testing on slave address " + str(self.address))
        found = False
        if int.from_bytes(self.address, byteorder="big") not in locks:
            locks[int.from_bytes(self.address, byteorder="big")] = threading.Lock()

        with locks[int.from_bytes(self.address, byteorder="big")]:
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
            mbdev.serial.timeout = 0.4
            mbdevs[int.from_bytes(self.address, byteorder="big")] = mbdev
        try:
            test: bool = True
            test = test and self.get_field("type")
            test = test and self.get_field("hardware_name")
            test = test and self.get_field("hardware_version")
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
        mbdev = mbdevs[int.from_bytes(self.address, byteorder="big")]
        modbus_version = self.get_modbus_version()
        with locks[int.from_bytes(self.address, byteorder="big")]:
            try:
                if modbus_version == Version("1.0.0"):
                    serial_number = mbdev.read_string(21, 6).strip('\x00')
                    return serial_number
                else:
                    logger.error(f"iRock Modbus Version ({modbus_version}) in get_settings not supported")
                self.serial_number = serial_number
            except Exception as e:
                logger.error(f"Can't get iRock settings: {e}")
        return self.serial_number

    def get_settings(self):
        mbdev = mbdevs[int.from_bytes(self.address, byteorder="big")]
        modbus_version = self.get_modbus_version()
        with locks[int.from_bytes(self.address, byteorder="big")]:
            try:
                if modbus_version == Version("1.0.0"):
                    cell_count = mbdev.read_register(35)
                    capacity = mbdev.read_float(36, byteorder=3)
                else:
                    logger.error(f"iRock Modbus Version ({modbus_version}) in get_settings not supported")
                    return False
                self.cell_count = cell_count
                self.capacity = capacity
                logger.debug(f"iRock Cell Count is {cell_count}")
                logger.debug(f"iRock Capacity is {capacity}")
            except Exception as e:
                logger.warn(f"Can't get iRock settings: {e}")
                return False

        with locks[int.from_bytes(self.address, byteorder="big")]:
            try:
                if modbus_version == Version("1.0.0"):
                    max_battery_charge_current = mbdev.read_float(46, byteorder=3)
                    max_battery_discharge_current = mbdev.read_float(48, byteorder=3)
                    hardware_version = mbdev.read_string(17, 4).strip('\x00')
                    hardware_name = mbdev.read_string(9, 8).strip('\x00')
                    serial_number = mbdev.read_string(21, 6).strip('\x00')
                    max_battery_voltage = utils.MAX_CELL_VOLTAGE * self.cell_count
                    min_battery_voltage = utils.MIN_CELL_VOLTAGE * self.cell_count
                else:
                    logger.error(f"iRock Modbus Version ({modbus_version}) in get_settings not supported")
                    return False
                self.max_battery_charge_current = max_battery_charge_current
                self.max_battery_discharge_current = max_battery_discharge_current
                self.hardware_version = hardware_version
                self.hardware_name = hardware_name
                self.serial_number = serial_number
                self.max_battery_voltage = max_battery_voltage
                self.min_battery_voltage = min_battery_voltage
                logger.debug(f"iRock Maximal Battery Charge Current is {max_battery_charge_current}")
                logger.debug(f"iRock Maximal Battery Discharge Current is {max_battery_discharge_current}")
                logger.debug(f"iRock Hardware Version is {hardware_version}")
                logger.debug(f"iRock Hardware Name is {hardware_name}")
                logger.debug(f"iRock Serial Number is {serial_number}")
                logger.debug(f"iRock Maximal Battery Voltage is {max_battery_voltage}")
                logger.debug(f"iRock Minimal Battery Voltage is {min_battery_voltage}")
            except Exception as e:
                logger.error(f"Can't get iRock settings: {e}")
                return False

        if len(self.cells) == 0:
            for _ in range(self.cell_count):
                self.cells.append(Cell(False))

        return True

    def refresh_data(self):
        result = self.read_status_data()
        result = result and self.read_cell_data()
        return result

    def read_status_data(self):
        mbdev = mbdevs[int.from_bytes(self.address, byteorder="big")]
        modbus_version = self.get_modbus_version()
        with locks[int.from_bytes(self.address, byteorder="big")]:
            try:
                if modbus_version == Version("1.0.0"):
                    voltage = mbdev.read_float(38, byteorder=3)
                    current = mbdev.read_float(40, byteorder=3)
                    soc = mbdev.read_float(42, byteorder=3)
                    temp_1 = mbdev.read_float(54, byteorder=3)
                    temp_2 = mbdev.read_float(56, byteorder=3)
                    temp_3 = mbdev.read_float(58, byteorder=3)
                    temp_4 = mbdev.read_float(60, byteorder=3)
                    charge_fet = True
                    discharge_fet = True
                else:
                    logger.error(f"iRock Modbus Version ({modbus_version}) in get_settings not supported")
                    return False
                self.voltage = voltage
                self.current = current
                self.soc = soc
                self.temp_1 = self.to_temp(1, temp_1)
                self.temp_2 = self.to_temp(2, temp_2)
                self.temp_3 = self.to_temp(3, temp_3)
                self.temp_4 = self.to_temp(4, temp_4)
                self.charge_fet = charge_fet
                self.discharge_fet = discharge_fet
            except Exception as e:
                logger.error(f"Can't get iRock settings: {e}")
                return False
        return True

    def read_cell_data(self):
        mbdev = mbdevs[int.from_bytes(self.address, byteorder="big")]
        modbus_version = self.get_modbus_version()
        with locks[int.from_bytes(self.address, byteorder="big")]:
            try:
                for c in range(self.cell_count):
                    if modbus_version == Version("1.0.0"):
                        voltage = mbdev.read_float(64 + c * 4, byteorder=3)
                        balance = mbdev.read_register(66 + c * 4)
                    else:
                        logger.error(f"iRock Modbus Version ({modbus_version}) in read_cell_data not supported")
                        return False
                    self.cells[c].voltage = voltage
                    self.cells[c].balance = balance
            except Exception as e:
                logger.error(f"Can't get iRock Cell Data: {e}")
                return False
        return True
    
    def get_modbus_version(self) -> Version:
        mbdev = mbdevs[int.from_bytes(self.address, byteorder="big")]

        with locks[int.from_bytes(self.address, byteorder="big")]:
            try:
                modbus_version = Version.coerce(str(mbdev.read_string(1, 8).strip('\x00')))
                logger.debug(f"iRock ModBus Version is {str(modbus_version)}")
                return modbus_version
            except Exception as e:
                logger.warn(f"Can't get iRock Modbus Version: {e}")
    
    def get_field(self, name: str) -> bool:
        mbdev = mbdevs[int.from_bytes(self.address, byteorder="big")]
        modbusVersion = self.get_modbus_version()

        if modbusVersion in MODBUS_VERSIONS:
            for modbusRegister in MODBUS_REGISTERS:
                if modbusRegister["version"] == modbusVersion:
                    for fieldname, data in modbusRegister["register"][name].items():
                        if fieldname == name:
                            if name in HARDWARE_FUNCTIONS[self.type] or self.type == "iRock":
                                with locks[int.from_bytes(self.address, byteorder="big")]:
                                    try:
                                        if modbusRegister["type"] == str:
                                            result = mbdev.read_string(data["address"], data["length"]).strip('\x00')
                                        if modbusRegister["type"] == int:
                                            result = mbdev.read_register(data["address"])
                                        if modbusRegister["type"] == float:
                                            result = mbdev.read_float(data["address"], number_of_registers= data["length"], byteorder=3)
                                        if modbusRegister["type"] == Version:
                                            result = Version.coerce(str(mbdev.read_string(data["address"], data["length"]).strip('\x00')))
                                        setattr(self, name, result)
                                        logger.debug(f"iRock field {name}: {result}")
                                        return True
                                    except Exception as e:
                                        logger.warn(f"Can't get iRock field {name}: {e}")
                            else:
                                logger.warn(f"iRock field {name} not supported for {self.type}")
                    logger.warn(f"iRock field {name} not found")
        else:
            logger.warn(f"ModBus Version {modbusVersion} not supported")
        return False
