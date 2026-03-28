import adafruit_logging as logging
from ac_base import ac_base
from ac_base import CustomStreamHandler
import adafruit_hts221
import microcontroller

class ac_temp():
    def __init__(self, i2c, self_test=False):
        self.self_test = self_test
        self.self_test_list = [70.5, 70.15, 70.05, 70, 69.95, 69.85, 69.5, 69.85, 69.96, 70, 70.05, 70.15, 70.5, 71, 72] + [0] * 100
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        self.logger.addHandler(CustomStreamHandler())
        self.initialized = False
        self.self_test_loop_count = 0
        try:
            self.hts221 = adafruit_hts221.HTS221(i2c)
            self.logger.info(f'Temperature/humidity monitor hts221 initialilzed.')
            self.initialized = True
        except Exception as e:
            self.logger.error(f'hts221 initialization failure: {e}')

    def get_temp(self):
        if self.initialized:
            try:
                if self.self_test:
                    ac_base.temp = self.self_test_list[0]
                    self.self_test_loop_count += 1
                    if self.self_test_loop_count % 15 == 0:
                        self.self_test_list = self.self_test_list[1:] + [self.self_test_list[0]]
                else:
                    ac_base.temp = self.hts221.temperature * (9/5) + 32
                ac_base.rh = self.hts221.relative_humidity
                ac_base.cpu_temp = microcontroller.cpu.temperature * (9/5) + 32
                self.logger.debug(f'temp: {ac_base.temp:.1f}F rh: {ac_base.rh:.2f} cpu_temp: {ac_base.cpu_temp:.1f}F\n')
            except Exception as e:
                self.logger.error(f'Read temp error: {e}')
                ac_base.temp = float('nan')
