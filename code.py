
""" Ruminations regarding controlling the AC and the fans.
    The ON/OFF button of the display is of course the first control.
    The AC should be driven off the differential between the set point and the measured temp.   With
    some regard for the fans.   If the fans were off, the mechanical layout of the AC ducts should
    provide for some air flow.  Probably get away with simply leaving out an interlock for making sure
    the fans are running before enabling the compressor.   This should tested.
    
    Would like to minimize the fan activity for noise and efficiency purposes.   At the same time need to 
    be sure and keep the air circulating for uniform temps in the room and to make sure the temperature
    sensor is reading room temp."""

""" Set up PID to run off setpoint minus measured temp.   Expect the time constant of the room to be measured
    in minutes.  Setup PID to rail between +1 and -1.   Downstream devices can scale/offset this as necessary.
    Apparently, the integral term integrates over all time.  This means there will be some overshoot in order
    to get the integral term back to zero.   Assume nomial temperature variations of less than a degree F.
    However, when a door is opened, there will probably be a large temp change.   Compressor proobably goes
    to max.   There is quite a bit thermal mass in the room.  Should head back to setpoint fairly quickly.
    """

"""Real python has issues with gracefully exiting on keyboard interrupt with asyncio.
   Basic problem is cancelled tasks need to run to complete, but async loop is dead.
   Real python can field a signal, cancel all tasks, then run the async loop to let them finish.
   circuitpython does not have signal module, so we just catch keyboard interrupt and exit.
   Apparently, the exit cancels all tasks.   Its difficult to know what circuitpython does under the hood."""



import asyncio
import adafruit_logging as logging
import busio
import board
from ac_display import AcDisplay
from ac_network import ac_network
from ac_temp import ac_temp
from ac_base import ac_base
from ac_fans import ac_fans
from ac_base import CustomStreamHandler
from ac_modbus import ac_modbus
import time  
import neopixel
from simple_pid import PID #type: ignore
import supervisor
import os
import gc
import math

I2C_BATT_MON = os.getenv("I2C_BATT_MON", 54)
I2C_HTS221_TEMP_HUM = os.getenv("I2C_HTS221_TEMP_HUM", 95) 
I2C_FOCALTOUCH = os.getenv("I2C_FOCALTOUCH", 56)
I2C_24LC32 = os.getenv("I2C_24LC32", 80)
i2c_dict = {54: "BATT_MON",
            95: "HTS221_TEMP_HUM",
            56: "FOCALTOUCH",
            80: "24LC32_NV"}

MC_LOOP_DELAY = 1
loop_secs = MC_LOOP_DELAY * 1

TEMPS_PERIOD = os.getenv("TEMPS_PERIOD", 6)

SELF_TEST_MODE = os.getenv("SELF_TEST_MODE", "false").lower() == "true"

async def led_loop():
    pixels = neopixel.NeoPixel(board.NEOPIXEL, 1)
    while True:
        pixels[0] = (255, 0, 0)
        await asyncio.sleep(0.5)
        pixels[0] = (0, 255, 0)
        await asyncio.sleep(0.5)
        pixels[0] = (0, 0, 255)
        await asyncio.sleep(0.5)  

async def run_tasks(task_list):
    await asyncio.gather(*task_list)

class ac_master_cylinder(ac_base):
    def __init__(self):
        self.pid = PID(Kp=-1, Ki=-0.00, Kd=-0.00, setpoint=ac_base.temp_set_point, sample_time = None,
                       output_limits = (-1, 1), starting_output = 0)

    async def loop(self):
        loop_counter = 0
        last_supervisor_ticks = None
        if SELF_TEST_MODE:
            logger.info(f'{SELF_TEST_MODE=}')
        last_temps_period = None
        auto_on_status = display.read_nv("auto_on")
        if auto_on_status == None:
            logger.info(f'auto_on status is None.  No EEPROM. defaulting to off.')
        elif auto_on_status == False:
            logger.warning(f'auto_on status is False.  EEPROM hash failure. defaulting to off.')
        elif int.from_bytes(auto_on_status, "big") == 0: 
            set_point = display.read_nv("set_point") 
            if set_point == None or set_point == False: 
                logger.error(f'set_point is {set_point}.  Missing EEPROM or hash failure. defaulting off.')
            else:
                ac_base.temp_set_point = int.from_bytes(set_point, "big")
                display.on_off_button_press("set_on")   
                display.auto_on_button_press("button_on")

        while True:

            if loop_counter % loop_secs == 0: 

                temp.get_temp()
                self.pid.setpoint = ac_base.temp_set_point

                minutes = self.get_minutes()
                if minutes % TEMPS_PERIOD == 0:
                    if last_temps_period != minutes or last_temps_period is None:
                        last_temps_period = minutes
                        display.temps_line[display.temps_index] = display.temp if not math.isnan(display.temp) else 70
                        display.gen_temps_plot(True)

                if last_supervisor_ticks is None:
                    last_supervisor_ticks = supervisor.ticks_ms()
                    ms_per_loop = None
                else:
                    ms_per_loop = (supervisor.ticks_ms() - last_supervisor_ticks)//loop_secs
                last_supervisor_ticks = supervisor.ticks_ms()

                ac_base.temp_err = ac_base.temp_set_point - ac_base.temp 
                if not math.isnan(ac_base.temp):
                    ac_base.pid_demand = self.pid(ac_base.temp)

            if loop_counter % 5 == 0:      
                logger.debug(f'ms/loop: {ms_per_loop} mem_free: {gc.mem_free()} temp_err:{ac_base.temp_err:.2f}' + 
                             f' pid: {ac_base.pid_demand:.2f} rpm: {modbus.read_rpm()}'+
                             f' fans: {ac_base.fan_rpm}')

            loop_counter += 1  # seconds from boot, infinite integers
            ac_base.compressor_rpm = modbus.read_rpm()
            await asyncio.sleep(MC_LOOP_DELAY)
                
if __name__ == "__main__":

    logger = logging.getLogger(__name__)
    logger.addHandler(CustomStreamHandler())
    logger.setLevel(logging.DEBUG)

# No i2c, doesn't make sense to continue.
    i2c = busio.I2C(board.SCL, board.SDA, frequency=400000)
    i2c_list = []
    while not I2C_HTS221_TEMP_HUM in i2c_list:
        logger.info(f'Scanning I2C bus.')
        try:
            i2c.try_lock()
            i2c_list = i2c.scan()
            i2c_devices = ""
            for ii in i2c_list:
                i2c_devices += i2c_dict[ii]
                if ii != i2c_list[-1]: i2c_devices += " "
            logger.info(f'I2C devices found: {i2c_devices}')
            i2c.unlock()
            continue
        except ValueError as ve:
            logger.error(f'I2C setup ValueError: {ve}.')
        except Exception as e:
            logger.error(f'I2C setup exception: {e}.')
        finally:
            i2c.unlock()
            time.sleep(5)
 
    task_list = [asyncio.create_task(led_loop())]

    temp = ac_temp(i2c, SELF_TEST_MODE)
    if temp.initialized:
        logging.getLogger('ac_temp').setLevel(logging.INFO) 

    display = AcDisplay(i2c, SELF_TEST_MODE) 
    if display.initialized:
        logging.getLogger('ac_display').setLevel(logging.DEBUG)
        logging.getLogger('touch').setLevel(logging.INFO)
        logging.getLogger('lite').setLevel(logging.INFO)
        logging.getLogger('ac_non_volatile').setLevel(logging.INFO)
        task_list.append(asyncio.create_task(display.lite_loop()))
        if display.ft is not None:
            task_list.append(asyncio.create_task(display.get_touch()))


    network = ac_network()
    if network.ethernet:
        logging.getLogger('ac_network').setLevel(logging.INFO)
        logging.getLogger('ntp_logger').setLevel(logging.INFO)
        logging.getLogger('post_logger').setLevel(logging.INFO)
        task_list.append(asyncio.create_task(network.fetch_ntp()))
        task_list.append(asyncio.create_task(network.post_temp()))  

    fan = ac_fans()
    logging.getLogger('ac_fans').setLevel(logging.DEBUG)
    task_list.append(asyncio.create_task(fan.fan_loop()))
    #task_list.append(asyncio.create_task(fan.characterize_fans()))

    modbus = ac_modbus()
    logging.getLogger('ac_modbus').setLevel(logging.INFO)
    task_list.append(asyncio.create_task(modbus.ac_loop()))

    master_cylinder = ac_master_cylinder()
    task_list.append(asyncio.create_task(master_cylinder.loop()))

    try:
        asyncio.run(run_tasks(task_list))
    except KeyboardInterrupt:
        print("Program interrupted by user (Ctrl+C).")
    finally:
        print("Exiting program.")
