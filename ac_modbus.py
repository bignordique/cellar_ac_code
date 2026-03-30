""" Controls the Rigid AC via the modbus protocol over RS-232.
    Master Cylinder stores PID result at ac_base.pid_demand.
    ac_loop samples ac_base.pid_demand.   Greater than zero, set
    compressor RPM proportionally.   If less than 0 but greater 
    than -DEADBAND, set compressor to minimum.   If less than
    -DEADBAND turn compressor off.   As the temperature rises,
    turn compressor on when
    ac_base.pid_demand is greater than zero.   Hysteresis. """

from umodbus.serial import Serial as ModbusRTUMaster #type: ignore
from ac_base import ac_base
from ac_base import CustomStreamHandler
import board
import digitalio
import asyncio
import adafruit_logging as logging
import os
import math

POW_EN_PIN = board.D5
TEST_ERR_REGS = False  # Not the greatest test.   Can't really inject errors.

host = ModbusRTUMaster(
    tx_pin=board.TX,
    rx_pin=board.RX,
    baudrate = 9600,
    data_bits = 8,
    stop_bits = 1,
    parity = None,
)

SLAVE_ADDR = 1

# From Rigid Communication protocol MODBUS RTU:
""" Register Addr described in this document is (1 + protocol address), which means that the address
    used in modbus pacaket is (register addr - 1)  """

reg_dict = {"Control_Mode" : 1000,
            "Control" : 1001,
            "RPM_set" :  1002,
            "Direction" : 1003,
            "RPM_speed" : 2000,
            "Fault1" : 2001,
            "Fault2" : 2002,
            "Warning1" : 2003,
            "Warning2" : 2004,
            "Bus_Voltage"  : 2005,
            "Output_Current" : 2006,
            "Amb_Temp" : 2007,
            "Module_Temp" : 2008}

COMM_MODE = 0              # Control via RS232

# Spec says "Speed scope: 2000-6000"
# Speedup Time 30s
MAX_COMP_RPM = 4500  #Limited by controller power of 150 watts.  Determined expirically.
MIN_COMP_RPM = 2000
COMP_RPM_RANGE = MAX_COMP_RPM - MIN_COMP_RPM

DEADBAND = float(os.getenv("COMPRESSOR_DEADBAND", 0.1))

LOOP_PERIOD = 1
POW_ON_DELAY = 5
POW_OFF_DELAY = 5
RPM_SET_DELAY = 5

class ac_modbus(ac_base):
    def __init__(self):
        self.pow_en = digitalio.DigitalInOut(POW_EN_PIN)
        self.pow_en.direction = digitalio.Direction.OUTPUT
        self.pow_en.value = False
        self.pow_valid = False

        self.logger = logging.getLogger(__name__)
        self.logger.addHandler(CustomStreamHandler())
        self.logger.setLevel(logging.INFO)

        self.logger.info(f'AC Modbus initialized.')

    async def pow_on(self):
        if not self.pow_valid:
            self.pow_en.value = True
            await asyncio.sleep(POW_ON_DELAY)
            self.pow_valid = True
            self.logger.debug(f'AC Modbus pow_valid is True')
            self.write_single_reg("Control_Mode", COMM_MODE)
            self.write_single_reg("Control", 0)

    async def pow_off(self):
        if self.pow_valid:
            self.pow_en.value = False
            self.pow_valid = False
            self.logger.debug(f'AC Modbus pow_valid is False')
            await asyncio.sleep(POW_OFF_DELAY)

    def read_all_regs(self):
        if self.pow_valid:
            report = f'Control Mode: {self.read_holding_reg("Control_Mode")}\n'
            report += f'Control: {self.read_holding_reg("Control")}\n'
            report += f'RPM set: {self.read_holding_reg("RPM_set")}\n'
            report += f'Direction: {self.read_holding_reg("Direction")}\n'
            report += f'RPM speed: {self.read_holding_reg("RPM_speed")}\n'
            report += f'Fault1: {self.read_holding_reg("Fault1")}\n'
            report += f'Fault2: {self.read_holding_reg("Fault2")}\n'
            report += f'Warning1: {self.read_holding_reg("Warning1")}\n'
            report += f'Warning2: {self.read_holding_reg("Warning2")}\n'
            report += f'Bus Voltage: {self.read_holding_reg("Bus_Voltage")}\n'
            report += f'Output Current: {self.read_holding_reg("Output_Current")/100}\n'
            report += f'Amb Temp: {self.read_holding_reg("Amb_Temp")//10}\n'
            report += f'Module Temp: {self.read_holding_reg("Module_Temp")//10}'
        else: report = f'Compressor power not valid.'
        return report

    def read_holding_reg(self, reg_name):
        if self.pow_valid:
            try:
                reg_data = host.read_holding_registers(SLAVE_ADDR, reg_dict[reg_name], 1)[0]
                if (reg_name == "Fault1" or reg_name == "Fault2" or reg_name == "Warning1") and TEST_ERR_REGS:
                    return 1
                else:
                    return reg_data
            except Exception as e:
                self.logger.error(f'Error reading register: {reg_name} - {e}')
        return False
    
    def write_single_reg(self, reg_name, reg_data):
        if self.pow_valid:
            self.logger.debug(f'Writing {reg_name} with {reg_data}')
            try:
                return host.write_single_register(SLAVE_ADDR, reg_dict[reg_name], reg_data)
            except Exception as e:
                self.logger.error(f'Error writing register: {reg_name} - {e}')
        return False
    
    async def write_rpm_set(self, rpm_value):
        if rpm_value == 0:
            self.write_single_reg("Control", 0)
        else:
            self.write_single_reg("RPM_set", rpm_value)
            self.write_single_reg("Control", 1)
        await asyncio.sleep(RPM_SET_DELAY)

    def read_rpm(self):
        if  self.pow_en.value:
           return self.read_holding_reg("RPM_speed")
        else: return None

    def compressor_power(self):
        bus_voltage = self.read_holding_reg("Bus_Voltage")
        if bus_voltage == False: bus_voltage = 0
        output_current = self.read_holding_reg("Output_Current")
        if output_current == False:
            output_current = 0
        else:
            output_current = output_current/100
        return f'volts: {bus_voltage} current: {output_current} pow: {bus_voltage*output_current}'

    async def ac_loop(self):
        self.logger.info(f'Starting ac_loop.')
        while True:
            if not ac_base.ac_enable or math.isnan(ac_base.temp):
                await self.pow_off()
            else:
                if ac_base.pid_demand is not None:
                    pid_rpm = int(ac_base.pid_demand * COMP_RPM_RANGE + MIN_COMP_RPM)

                    if not self.pow_valid:
                        if ac_base.pid_demand >= 0:
                            await self.pow_on()
                            await self.write_rpm_set(pid_rpm)
                    else:
                        if ac_base.pid_demand < -DEADBAND:
                            await self.pow_off()
                        else:
                            if ac_base.pid_demand < 0:
                                await self.write_rpm_set(MIN_COMP_RPM)
                            else:
                                await self.write_rpm_set(pid_rpm)

                rigid_ac_Fault1 = self.read_holding_reg("Fault1")
                if rigid_ac_Fault1 != 0:
                    self.logger.warning(f'Rigid AC Fault1 is not zero: {rigid_ac_Fault1}')
                    self.logger.debug(self.read_all_regs())
                rigid_ac_Fault2 = self.read_holding_reg("Fault2")
                if rigid_ac_Fault2 != 0:
                    self.logger.warning(f'Rigid AC Fault2 is not zero: {rigid_ac_Fault2}')
                    self.logger.debug(self.read_all_regs())
                rigid_ac_Warning1 = self.read_holding_reg("Warning1")
                if rigid_ac_Warning1 != 0:
                    self.logger.warning(f'Rigid AC Warning1 is not zero: {rigid_ac_Warning1}')
                    self.logger.info(self.compressor_power())
                    self.logger.debug(self.read_all_regs())
                self.logger.debug(f'{self.pow_valid=} {ac_base.pid_demand=} {pid_rpm=}')

            #self.logger.info(self.read_all_regs())

            await asyncio.sleep(LOOP_PERIOD)   

        

