# Probably don't need the PID.   But what't the fun in that?
# Not sure best method for setting PID parameters.
# Even a small (0.1) Ki seems to cause a great deal of overshoot??
# Kd doesn't seem to do much??
# Kp of 0.8 seems to give reasonable results.

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
import math

# 100% PWM seems to mess up the fans??   Just use 0.99 max.

FAN_LOOP_DELAY = 1
FAN_BURST_CYCLE = 30 * 60 // FAN_LOOP_DELAY
FAN_BURST_LENGTH = 5 * 60 // FAN_LOOP_DELAY
PID_CYCLE = 10 // FAN_LOOP_DELAY
PID_SETTLE_LENGTH = 5 // FAN_LOOP_DELAY

DEADBAND = float(os.getenv("FAN_DEADBAND", 0.01))

Kp = float(os.getenv("FAN_KP", "0.5"))
Ki = float(os.getenv("FAN_KI", "0.00"))
Kd = float(os.getenv("FAN_KD", "0.01"))

FAN_MIN_RPM = os.getenv("FAN_MIN_RPM", 1250)
FAN_MAX_RPM = os.getenv("FAN_MAX_RPM", 5500) 
FAN_PWM_PER_RPM0 = float(os.getenv("FAN_PWM_PER_RPM0", "9.2"))
FAN_PWM_PER_RPM1 = float(os.getenv("FAN_PWM_PER_RPM1", "9.9"))
FAN_RPM_RANGE = FAN_MAX_RPM - FAN_MIN_RPM
FAN_BURST_RPM = os.getenv("FAN_BURST_RPM_PERCENT", 50)/100 * FAN_MAX_RPM

FAN_TACH_CYCLES_PER_ROTATION = 2
POW_ON_DELAY = 1
POW_OFF_DELAY = 5

pow_en = digitalio.DigitalInOut(board.D6)
pow_en.direction = digitalio.Direction.OUTPUT
pow_en.value = False

fan_pwm0 = pwmio.PWMOut(board.A0, frequency = 25000, duty_cycle = 0)
fan_pwm1 = pwmio.PWMOut(board.A2, frequency = 25000, duty_cycle = 0)

fan_tach0 = countio.Counter(board.A1, edge=countio.Edge.RISE, pull=digitalio.Pull.UP)
fan_tach1 = countio.Counter(board.A3, edge=countio.Edge.RISE, pull=digitalio.Pull.UP)

class ac_fans(ac_base):
    def __init__(self):

        self.logger = logging.getLogger(__name__)
        self.logger.addHandler(CustomStreamHandler())
        self.logger.setLevel(logging.INFO)
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
            ac_base.fan_rpm = [None, None]
            self.logger.info(f'Fans power off.')
            await asyncio.sleep(POW_OFF_DELAY)

    async def fan_loop(self):

        self.logger.info(f'Starting fan_loop.')

        while True:

            if not ac_base.ac_enable:
                last_pid_rpm = 0
                fan_loop_base = 0
                burst_stop = FAN_BURST_CYCLE
                fan_pwm0.duty_cycle = 0
                fan_pwm1.duty_cycle = 0
                await self.fan_pow_off()
            else:

                pid_rpm = 0
                if not math.isnan(ac_base.temp):
                    if ac_base.pid_demand >= 0:
                        pid_rpm = ac_base.pid_demand * FAN_RPM_RANGE + FAN_MIN_RPM
                    elif pow_en.value and ac_base.pid_demand > -DEADBAND and last_pid_rpm > pid_rpm :
                        pid_rpm = FAN_MIN_RPM
                if pid_rpm == 0 and last_pid_rpm != 0:
                    target_rpm = 0
                last_pid_rpm = pid_rpm


                if pid_rpm != 0:
                    fan_loop_base = FAN_BURST_CYCLE - FAN_BURST_LENGTH
                    burst_stop = FAN_BURST_CYCLE
                
                if fan_loop_base == 0 :
                        target_rpm = FAN_BURST_RPM
                        burst_stop = fan_loop_base + FAN_BURST_LENGTH

                if fan_loop_base == burst_stop :
                        target_rpm = 0

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
                        fan_tach0.reset()
                        fan_tach1.reset()

                    if pid_set:
                        elapsed_time = (time.monotonic_ns() - start_timestamp)/1e9
                        fan_rpm0 = int(fan_tach0.count*60/(FAN_TACH_CYCLES_PER_ROTATION * elapsed_time))
                        fan_rpm1 = int(fan_tach1.count*60/(FAN_TACH_CYCLES_PER_ROTATION * elapsed_time))
                        rpm_error0 = target_rpm - fan_rpm0
                        rpm_error1 = target_rpm - fan_rpm1
                        rpm_adjust0 = self.fan_pid0(fan_rpm0)
                        rpm_adjust1 = self.fan_pid1(fan_rpm1)
                        pwm_adjust0 = rpm_adjust0 * FAN_PWM_PER_RPM0
                        pwm_adjust1 = rpm_adjust1 * FAN_PWM_PER_RPM1
                        current_pwm0 = current_pwm0 + int(pwm_adjust0)
                        current_pwm1 = current_pwm1 + int(pwm_adjust1)
                        fan_pwm0.duty_cycle = current_pwm0
                        fan_pwm1.duty_cycle = current_pwm1
                        ac_base.fan_rpm[0] = int(fan_rpm0)
                        ac_base.fan_rpm[1] = int(fan_rpm1)
                        self.logger.debug(f'RPM: {fan_rpm0, fan_rpm1}, target: {target_rpm}, error: {rpm_error0, rpm_error1} adjust: {rpm_adjust0, rpm_adjust1}')
                    fan_pid_base += 1 

                fan_loop_base = (fan_loop_base + 1) % FAN_BURST_CYCLE

            await asyncio.sleep(FAN_LOOP_DELAY)


    async def characterize_fans(self):
        pwm = 0
        fan_number = 0
        results = {}
        await self.fan_pow_on()
        while True:
            fan_pwm0.duty_cycle=0
            fan_pwm1.duty_cycle=0
            await asyncio.sleep(5)
            #for pwm in range(0, 11*6553, 6553):
            #for pwm in range(0, 11*655, 655):
            for pwm in range(10000, 10005, 1):
                eval("fan_pwm"+str(fan_number)).duty_cycle = 0
                await asyncio.sleep(10)
                eval("fan_pwm"+str(fan_number)).duty_cycle = pwm
                await asyncio.sleep(3)  # ramp up time
                start_timestamp = time.monotonic_ns()
                eval("fan_tach"+str(fan_number)).reset()
                await asyncio.sleep(5)  # sample time
                elapsed_time_ms = (time.monotonic_ns() - start_timestamp)/1e6
                fan_rpm = int(eval("fan_tach"+str(fan_number)).count * 60000/(FAN_TACH_CYCLES_PER_ROTATION * elapsed_time_ms))
                pwm_per_rpm = pwm/fan_rpm if fan_rpm != 0 else 0
                if pwm in results:
                    results[pwm].append(fan_rpm)
                    results[pwm].append(pwm_per_rpm)
                else:
                    results[pwm] = [fan_rpm, pwm_per_rpm]
            fan_number = (fan_number + 1) % 2
            for key, value in sorted(results.items()):
                out_str = ""
                vcount = 0
                for value in results[key]:
                    if vcount %2 == 0:
                        out_str = out_str + f' {value:>5}'
                    else:
                        out_str = out_str + f' {value:>4.1f}'
                    if vcount %4 == 3:
                        out_str += " | "
                    vcount += 1

                print (f'{key:>5}', "-", out_str)









