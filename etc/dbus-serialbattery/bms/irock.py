# -*- coding: utf-8 -*-

# NOTES
# Please see "Add/Request a new BMS" https://mr-manuel.github.io/venus-os_dbus-serialbattery_docs/general/supported-bms#add-by-opening-a-pull-request
# in the documentation for a checklist what you have to do, when adding a new BMS

# avoid importing wildcards, remove unused imports
from battery import Battery, Cell
import logging
from utils import logger
import utils
import minimalmodbus
import serial
import threading
from typing import Dict
from semantic_version import Version

mbdevs: Dict[int, minimalmodbus.Instrument] = {}
locks: Dict[int, any] = {}

class iRock(Battery):
    def __init__(self, port, baud, address):
        super(iRock, self).__init__(port, baud, address)
        self.address = address
        self.type = self.BATTERYTYPE
        self.serial_number: str = None
        self.hardware_name: str = None

    BATTERYTYPE = "iRock"
    
    def custom_name(self) -> str:
        """
        Shown in the GUI under `Device -> Name`
        Overwritten, if the user set a custom name via GUI

        :return: the connection name
        """
        name: str = f"{self.type} ({self.serial_number})"
        return name
    
    def product_name(self) -> str:
        """
        Shown in the GUI under `Device -> Product`

        :return: the connection name
        """
        return f"{self.type}"
    
    def test_connection(self):
        """
        call a function that will connect to the battery, send a command and retrieve the result.
        The result or call should be unique to this BMS. Battery name or version, etc.
        Return True if success, False for failure
        """
        logger.debug("Testing on slave address " + str(self.address))
        found = False
        if int.from_bytes(self.address, byteorder="big") not in locks:
            locks[int.from_bytes(self.address, byteorder="big")] = threading.Lock()

        # TODO: We need to lock not only based on the address, but based on the port as soon as multiple BMSs
        # are supported on the same serial interface. Then locking on the port will be enough.

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
            # yes, 400ms is long but the BMS is sometimes really slow in responding, so this is a good compromise
            mbdev.serial.timeout = 0.4
            mbdevs[int.from_bytes(self.address, byteorder="big")] = mbdev
            
        modbus_version = self.get_modbus_version()
        with locks[int.from_bytes(self.address, byteorder="big")]:
            try:
                if modbus_version == Version("1.0.0"):
                    hardware_name = mbdev.read_string(9, 8).strip('\x00')
                    hardware_version = mbdev.read_string(17, 4).strip('\x00')
                    found = True
                    self.hardware_name = hardware_name
                    self.hardware_version = hardware_version
                    if self.hardware_name is not None:
                        self.type = self.hardware_name
                    logger.debug(f"Found iRock of type \"{self.hardware_name} {self.hardware_version}\" on port {self.port} ({self.address})")
                else:
                    logger.debug(f"Found iRock of type \"{self.hardware_name} {self.hardware_version}\" on port {self.port} ({self.address})")
                    logger.error(f"iRock ModBus Version not supported: {modbus_version}")
            except Exception as e:
                logger.debug(f"Testing failed for iRock on port {self.port} ({self.address}): {e}")

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
        """
        Used to identify a BMS when multiple BMS are connected
        Provide a unique identifier from the BMS to identify a BMS, if multiple same BMS are connected
        e.g. the serial number
        If there is no such value, please remove this function
        """
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
        """
        After successful connection get_settings() will be called to set up the battery
        Set all values that only need to be set once
        Return True if success, False for failure
        """

        mbdev = mbdevs[int.from_bytes(self.address, byteorder="big")]
        modbus_version = self.get_modbus_version()

        # MANDATORY values to set
        # does not need to be in this function, but has to be set at least once
        # could also be read in a function that is called from refresh_data()
        #
        # if not available from battery, then add a section in the `config.default.ini`
        # under ; --------- BMS specific settings ---------
        """
        # number of connected cells (int)
        self.cell_count = VALUE_FROM_BMS

        # capacity of the battery in ampere hours (float)
        self.capacity = VALUE_FROM_BMS
        """

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

        # OPTIONAL values to set
        # does not need to be in this function
        # could also be read in a function that is called from refresh_data()
        """
        # maximum charge current in amps (float)
        self.max_battery_charge_current = VALUE_FROM_BMS

        # maximum discharge current in amps (float)
        self.max_battery_discharge_current = VALUE_FROM_BMS

        # custom field, that the user can set in the BMS software (str)
        self.custom_field = VALUE_FROM_BMS

        # maximum voltage of the battery in V (float)
        self.max_battery_voltage_bms = VALUE_FROM_BMS

        # minimum voltage of the battery in V (float)
        self.min_battery_voltage_bms = VALUE_FROM_BMS

        # production date of the battery (str)
        self.production = VALUE_FROM_BMS

        # hardware version of the BMS (str)
        self.hardware_version = VALUE_FROM_BMS
        self.hardware_version = f"TemplateBMS {self.hardware_version} {self.cell_count}S ({self.production})"

        # serial number of the battery (str)
        self.serial_number = VALUE_FROM_BMS
        """
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

        # init the cell array once
        if len(self.cells) == 0:
            for _ in range(self.cell_count):
                self.cells.append(Cell(False))

        return True

    def refresh_data(self):
        """
        call all functions that will refresh the battery data.
        This will be called for every iteration (1 second)
        Return True if success, False for failure
        """
        result = self.read_status_data()

        # only read next dafa if the first one was successful
        result = result and self.read_cell_data()

        # this is only an example, you can combine all into one function
        # or split it up into more functions, whatever fits best for your BMS

        return result

    def read_status_data(self):

        mbdev = mbdevs[int.from_bytes(self.address, byteorder="big")]
        modbus_version = self.get_modbus_version()
        # Integrate a check to be sure, that the received data is from the BMS type you are making this driver for

        # MANDATORY values to set
        """
        # voltage of the battery in volts (float)
        self.voltage = VALUE_FROM_BMS

        # current of the battery in amps (float)
        self.current = VALUE_FROM_BMS

        # state of charge in percent (float)
        self.soc = VALUE_FROM_BMS

        # temperature sensor 1 in °C (float)
        temp1 = VALUE_FROM_BMS
        self.to_temp(1, temp1)

        # status of the battery if charging is enabled (bool)
        self.charge_fet = VALUE_FROM_BMS

        # status of the battery if discharging is enabled (bool)
        self.discharge_fet = VALUE_FROM_BMS
        """
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
        # OPTIONAL values to set
        """
        # remaining capacity of the battery in ampere hours (float)
        # if not available, then it's calculated from the SOC and the capacity
        self.capacity_remaining = VALUE_FROM_BMS

        # temperature sensor 2 in °C (float)
        temp2 = VALUE_FROM_BMS
        self.to_temp(2, temp2)

        # temperature sensor 3 in °C (float)
        temp3 = VALUE_FROM_BMS
        self.to_temp(3, temp3)

        # temperature sensor 4 in °C (float)
        temp4 = VALUE_FROM_BMS
        self.to_temp(4, temp4)

        # temperature sensor MOSFET in °C (float)
        temp_mos = VALUE_FROM_BMS
        self.to_temp(0, temp_mos)

        # status of the battery if balancing is enabled (bool)
        self.balance_fet = VALUE_FROM_BMS

        # PROTECTION values
        # 2 = alarm, 1 = warningm 0 = ok
        # high battery voltage alarm (int)
        self.protection.high_voltage = VALUE_FROM_BMS

        # low battery voltage alarm (int)
        self.protection.low_voltage = VALUE_FROM_BMS

        # low cell voltage alarm (int)
        self.protection.low_cell_voltage = VALUE_FROM_BMS

        # low SOC alarm (int)
        self.protection.low_soc = VALUE_FROM_BMS

        # high charge current alarm (int)
        self.protection.high_charge_current = VALUE_FROM_BMS

        # high discharge current alarm (int)
        self.protection.high_discharge_current = VALUE_FROM_BMS

        # cell imbalance alarm (int)
        self.protection.cell_imbalance = VALUE_FROM_BMS

        # internal failure alarm (int)
        self.protection.internal_failure = VALUE_FROM_BMS

        # high charge temperature alarm (int)
        self.protection.high_charge_temp = VALUE_FROM_BMS

        # low charge temperature alarm (int)
        self.protection.low_charge_temp = VALUE_FROM_BMS

        # high temperature alarm (int)
        self.protection.high_temperature = VALUE_FROM_BMS

        # low temperature alarm (int)
        self.protection.low_temperature = VALUE_FROM_BMS

        # high internal temperature alarm (int)
        self.protection.high_internal_temp = VALUE_FROM_BMS

        # fuse blown alarm (int)
        self.protection.fuse_blown = VALUE_FROM_BMS

        # HISTORY values
        # Deepest discharge in Ampere hours (float)
        self.history.deepest_discharge = VALUE_FROM_BMS

        # Last discharge in Ampere hours (float)
        self.history.last_discharge = VALUE_FROM_BMS

        # Average discharge in Ampere hours (float)
        self.history.average_discharge = VALUE_FROM_BMS

        # Number of charge cycles (int)
        self.history.charge_cycles = VALUE_FROM_BMS

        # Number of full discharges (int)
        self.history.full_discharges = VALUE_FROM_BMS

        # Total Ah drawn (lifetime) (float)
        self.history.total_ah_drawn = VALUE_FROM_BMS

        # Minimum voltage in Volts (lifetime) (float)
        self.history.minimum_voltage = VALUE_FROM_BMS

        # Maximum voltage in Volts (lifetime) (float)
        self.history.maximum_voltage = VALUE_FROM_BMS

        # Minimum cell voltage in Volts (lifetime) (float)
        self.history.minimum_cell_voltage = VALUE_FROM_BMS

        # Maximum cell voltage in Volts (lifetime) (float)
        self.history.maximum_cell_voltage = VALUE_FROM_BMS

        # Time since last full charge in seconds (int)
        self.history.time_since_last_full_charge = VALUE_FROM_BMS

        # Number of low voltage alarms (int)
        self.history.low_voltage_alarms = VALUE_FROM_BMS

        # Number of high voltage alarms (int)
        self.history.high_voltage_alarms = VALUE_FROM_BMS

        # Discharged energy in kilo Watt hours (int)
        self.history.discharged_energy = VALUE_FROM_BMS

        # Charged energy in kilo Watt hours (int)
        self.history.charged_energy = VALUE_FROM_BMS
        """
        return True

    def read_cell_data(self):

        mbdev = mbdevs[int.from_bytes(self.address, byteorder="big")]
        modbus_version = self.get_modbus_version()

        # MANDATORY values to set
        """
        # set voltage of each cell in volts (float)
        for c in range(self.cell_count):
            self.cells[c].voltage = VALUE_FROM_BMS
        """
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
        # OPTIONAL values to set
        """
        # set balance status of each cell, if available
        for c in range(self.cell_count):
            # balance status of the cell (bool)
            self.cells[c].balance = VALUE_FROM_BMS


        # set balance status, if only a common balance status is available (bool)
        # not needed, if balance status is available for each cell
        self.balancing: bool = VALUE_FROM_BMS
        if self.get_min_cell() is not None and self.get_max_cell() is not None:
            for c in range(self.cell_count):
                if self.balancing and (
                    self.get_min_cell() == c or self.get_max_cell() == c
                ):
                    self.cells[c].balance = True
                else:
                    self.cells[c].balance = False
        """

        return True
        
    def get_modbus_version(self) -> Version:
        mbdev = mbdevs[int.from_bytes(self.address, byteorder="big")]

        with locks[int.from_bytes(self.address, byteorder="big")]:
            try:
                modbus_version = Version.coerce(str(mbdev.read_string(1, 8).strip('\x00')))
                logger.debug(f"iRock ModBus Version is {str(modbus_version)}")
                return modbus_version

            except Exception as e:
                logger.warn(f"Can't get iRock Modbus Version {e}")