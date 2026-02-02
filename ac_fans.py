#Probably don't need the PID.   But what't the fun in that?
from ac_base import ac_base
from ac_base import CustomStreamHandler
import digitalio #type: ignore
import board #type: ignore
import time
import adafruit_logging as logging
import asyncio
import countio #type: ignore
import pwmio #type: ignore
from simple_pid import PID #type: ignore
import os

# For the Noctua NF-A12x25 PWM fans...
# Don't know what the fan max RPM is.   Set PWM to 0.99.   Somewhere around 4300 RPM.
# At 0.25 PWM, fan seems to be about 1200 RPM.
# 100% PWM seems to mess up the fans??   Just use 0.99 max.

FAN_POW_PIN = eval(os.getenv("FAN_POW_PIN", "board.D6"))
FAN_PWM_PINS = eval(os.getenv("FAN_PWM_PINS", "(board.A0, board.A2)"))
FAN_TACH_PINS = eval(os.getenv("FAN_TACH_PINS", "(board.A1, board.A3)"))
FAN_LOOP_DELAY = 1
FAN_BURST_CYCLE = 30 * 60 // FAN_LOOP_DELAY
FAN_BURST_LENGTH = 5 * 60 // FAN_LOOP_DELAY
PID_CYCLE = 10 // FAN_LOOP_DELAY
PID_SETTLE_LENGTH = 5 // FAN_LOOP_DELAY

DEADBAND = float(os.getenv("FAN_DEADBAND", 0.01))

Kp = float(os.getenv("FAN_KP", "0.5"))
Ki = float(os.getenv("FAN_KI", 0.00))
Kd = float(os.getenv("FAN_KD", 0.01))

MIN_FAN_PWM = os.getenv("MIN_FAN_PWM", 25)   # Percent
MAX_FAN_RPM = os.getenv("MAX_FAN_RPM", 6000) 
MIN_START_PWM = int(MIN_FAN_PWM/100 * 65535)
MAX_PWM = int(0.99 * 65535)
MIN_FAN_RPM = int(MIN_FAN_PWM/100 * MAX_FAN_RPM)
FAN_RPM_RANGE = MAX_FAN_RPM - MIN_FAN_RPM
FAN_PWM_RANGE = MAX_PWM - MIN_START_PWM
PWM_PER_RPM = FAN_PWM_RANGE / FAN_RPM_RANGE
FAN_TACH_CYCLES_PER_ROTATION = 2
POW_ON_DELAY = 1
POW_OFF_DELAY = 5

pow_en = digitalio.DigitalInOut(FAN_POW_PIN)
pow_en.direction = digitalio.Direction.OUTPUT
pow_en.value = False

class ac_fans(ac_base):
    def __init__(self):

        self.logger = logging.getLogger(__name__)
        self.logger.addHandler(CustomStreamHandler())
        self.logger.setLevel(logging.INFO)

        self.fan_pwm0 = pwmio.PWMOut(FAN_PWM_PINS[0], frequency = 25000, duty_cycle = 0) 
        self.fan_tach0 = countio.Counter(FAN_TACH_PINS[0], edge=countio.Edge.RISE, pull=digitalio.Pull.UP)
        self.fan_pwm1 = pwmio.PWMOut(FAN_PWM_PINS[1], frequency = 25000, duty_cycle = 0) 
        self.fan_tach1 = countio.Counter(FAN_TACH_PINS[1], edge=countio.Edge.RISE, pull=digitalio.Pull.UP)
        self.fan_pid0 = PID(Kp=Kp, Ki=Ki, Kd=Kd, setpoint=0, sample_time=None)
        self.fan_pid1 = PID(Kp=Kp, Ki=Ki, Kd=Kd, setpoint=0, sample_time=None)
    
    async def fan_pow_on(self):
        if not pow_en.value :
            pow_en.value = True
            self.logger.info(f'Fans power on.')
            await asyncio.sleep(POW_ON_DELAY)

    async def fan_pow_off(self):
        if pow_en.value :
            pow_en.value = False
            self.logger.info(f'Fans power off.')
            await asyncio.sleep(POW_OFF_DELAY)

    async def fan_loop(self):

        self.logger.info(f'Starting fan_loop.')

        while True:

            if not ac_base.ac_enable:
                fan_loop_base = 0
                self.fan_pwm0.duty_cycle = 0
                self.fan_pwm1.duty_cycle = 0
                await self.fan_pow_off()
            else:
                if fan_loop_base % FAN_BURST_CYCLE == 0 :
                    burst = True
                    burst_stop = fan_loop_base + FAN_BURST_LENGTH
                if fan_loop_base == burst_stop :
                    burst = False

                pid_rpm = 0
                if ac_base.pid_demand == 1 :
                    pid_rpm = MAX_FAN_RPM
                elif ac_base.pid_demand >= 0:
                    pid_rpm = ac_base.pid_demand * FAN_RPM_RANGE + MIN_FAN_RPM
                elif ac_base.pid_demand > - DEADBAND and pow_en.value:
                    pid_rpm = MIN_FAN_RPM

                target_rpm = MAX_FAN_RPM if burst else pid_rpm


                if target_rpm == 0:
                    await self.fan_pow_off()
                else: 
                    if not pow_en.value:
                        fan_pid_base = 0
                        start_timestamp = 0
                        current_pwm0 = 0
                        current_pwm1 = 0
                        self.fan_pid0.reset()
                        self.fan_pid1.reset()
                        await self.fan_pow_on()

                    pid_sample_start = False
                    pid_set = False
                    if fan_pid_base % PID_CYCLE == 0 :
                        pid_set = True
                        pid_set_mark = fan_pid_base + PID_SETTLE_LENGTH
                    if fan_pid_base == pid_set_mark :
                        pid_sample_start = True

                    self.fan_pid0.setpoint = target_rpm
                    self.fan_pid1.setpoint = target_rpm

                    if pid_sample_start:
                        start_timestamp = time.monotonic_ns()
                        self.fan_tach0.reset()
                        self.fan_tach1.reset()

                    if pid_set:
                        elapsed_time = (time.monotonic_ns() - start_timestamp)/1e9
                        fan_rpm0 = int(self.fan_tach0.count*60/(FAN_TACH_CYCLES_PER_ROTATION * elapsed_time))
                        fan_rpm1 = int(self.fan_tach1.count*60/(FAN_TACH_CYCLES_PER_ROTATION * elapsed_time))
                        rpm_error0 = target_rpm - fan_rpm0
                        rpm_error1 = target_rpm - fan_rpm1
                        rpm_adjust0 = self.fan_pid0(fan_rpm0)
                        rpm_adjust1 = self.fan_pid1(fan_rpm1)
                        pwm_adjust0 = rpm_adjust0 * PWM_PER_RPM
                        pwm_adjust1 = rpm_adjust1 * PWM_PER_RPM
                        current_pwm0 = max(MIN_START_PWM, min(current_pwm0 + int(pwm_adjust0), 65535)) 
                        current_pwm1 = max(MIN_START_PWM, min(current_pwm1 + int(pwm_adjust1), 65535)) 
                        self.fan_pwm0.duty_cycle = current_pwm0
                        self.fan_pwm1.duty_cycle = current_pwm1
                        ac_base.fan_rpm[0] = int(fan_rpm0)
                        ac_base.fan_rpm[1] = int(fan_rpm1)
                        self.logger.debug(f'RPM: {fan_rpm0, fan_rpm1}, target: {target_rpm}, error: {rpm_error0, rpm_error1} adjust: {rpm_adjust0, rpm_adjust1}')
                    fan_pid_base += 1 

                fan_loop_base += 1 

            await asyncio.sleep(FAN_LOOP_DELAY)




