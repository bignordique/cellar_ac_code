
import time
from collections import namedtuple
import board
import displayio
import terminalio
from adafruit_display_text.label import Label
from adafruit_bitmap_font import bitmap_font
from adafruit_display_shapes.line import Line
from adafruit_display_shapes.roundrect import RoundRect
from adafruit_button import Button
import bitmaptools
import adafruit_logging as logging
import asyncio
Coords = namedtuple("Point", "x y")

from ac_base import ac_base
from ac_base import CustomStreamHandler

import fourwire
import adafruit_ili9341
import adafruit_focaltouch
import pwmio

# Settings
BUTTON_HEIGHT = 60
BUTTON_MARGIN = 8
BUTTON_WIDTH = int((240 - 3 * BUTTON_MARGIN) / 2)
BLACK = 0x0
ORANGE = 0xFF8800
WHITE = 0xFFFFFF
GRAY = 0x888888
RED = 0xFF0000
GREEN = 0x00FF00
MAGENTA = 0xFF00FF

TEMPS_Y_EXTENT = ac_base.TEMPS_Y_SIZE - 2
TEMPS_Y_MIDLINE = ac_base.DISPLAY_Y_SIZE - ac_base.TEMPS_Y_SIZE//2 + 1
TEMPS_Y_TOP = ac_base.DISPLAY_Y_SIZE - ac_base.TEMPS_Y_SIZE

class ac_display(ac_base):

    def __init__(self, i2c, self_test)  -> None:
        super().__init__()
        self.i2c = i2c
        self.self_test = self_test

        self.logger = logging.getLogger(__name__)
        self.logger.addHandler(CustomStreamHandler())
        self.logger.setLevel(logging.INFO)

        self.touch_logger = logging.getLogger("touch")
        self.touch_logger.addHandler(CustomStreamHandler())
        self.touch_logger.setLevel(logging.INFO)

        self.lite_logger = logging.getLogger("lite")
        self.lite_logger.addHandler(CustomStreamHandler())
        self.lite_logger.setLevel(logging.INFO)

        self.disable_blink_count = 0

        self.lite = pwmio.PWMOut(board.D13, frequency = 1000, duty_cycle = 65535)

        displayio.release_displays()

        self.display = None

        self.initialized = False
        try:
            display_bus = fourwire.FourWire(board.SPI(),  command = board.A4, chip_select = board.A5)
            self.display = adafruit_ili9341.ILI9341(display_bus, rotation=90, width=ac_base.DISPLAY_X_SIZE, \
                                                    height=ac_base.DISPLAY_Y_SIZE)
            self.logger.info(f'ILI9341 connected through FourWire.')
            self.initialized = True
        except Exception as e:
            self.logger.error(f'Display not found. \n {e}')
            return
        self.display.auto_refresh = True

        self.ft = None 
        try:
            self.ft = adafruit_focaltouch.Adafruit_FocalTouch(i2c, debug=False)
            self.touch_logger.info(f'Adafruit_FocalTouch connected through i2c.')
        except Exception as e:
            self.touch_logger.error('FocalTouch not found. \n {e}')

# Make the display context
        self.group = displayio.Group()
        self.display.root_group = self.group

# Make a background color fill
        color_bitmap = displayio.Bitmap(ac_base.DISPLAY_X_SIZE, ac_base.DISPLAY_Y_SIZE, 1)
        color_palette = displayio.Palette(1)
        color_palette[0] = GRAY
        bg_sprite = displayio.TileGrid(color_bitmap,
                                       pixel_shader=color_palette,
                                       x=0, y=0)
        self.group.append(bg_sprite)

        self.temps_bitmap = displayio.Bitmap(ac_base.TEMPS_X_SIZE, ac_base.TEMPS_Y_SIZE, 2)
        temps_palette = displayio.Palette(2)
        temps_palette[0] = MAGENTA
        temps_palette[1] = GREEN
        temps_sprite = displayio.TileGrid(self.temps_bitmap,
                                          pixel_shader = temps_palette,
                                          x=0, y=ac_base.DISPLAY_Y_SIZE - ac_base.TEMPS_Y_SIZE)
        self.group.append(temps_sprite)

# Load the font
 #       self.font = bitmap_font.load_font("/fonts/Arial-Bold-24.bdf")
        self.buttons = []

        """box_border = RoundRect(20, 8, 200, 35, r=10, fill=WHITE, outline=BLACK, stroke=2)
        box_display = Label(self.font, x=100, y=8, text="XYZZY", color=ORANGE)
        box_display.y = 25"""

        first_line = 2 * BUTTON_HEIGHT + 3*BUTTON_MARGIN + 10
        self.time_display = Label(terminalio.FONT, x=8, y=first_line, color=WHITE)
        self.temp_rh_display = Label(terminalio.FONT, x=8, y=first_line+1*10, color=WHITE)
        self.cpu_temp_display = Label(terminalio.FONT, x=8, y=first_line+2*10, color=WHITE)
        self.rpm_display = Label(terminalio.FONT, x=8, y=first_line+3*10, color=WHITE)
        mid_line = Line(0, TEMPS_Y_MIDLINE, ac_base.DISPLAY_X_SIZE-1, TEMPS_Y_MIDLINE, WHITE)
        self.set_temp_display = Label(terminalio.FONT, x=8, y=TEMPS_Y_MIDLINE, color=WHITE, background_color=BLACK)
        self.set_hi_temp_display = Label(terminalio.FONT, x=8, y=TEMPS_Y_TOP, color=WHITE, background_color=BLACK)

        pos = self.button_grid(0, 1)
        set_point_box = RoundRect(pos.x, pos.y, BUTTON_WIDTH, BUTTON_HEIGHT, r=10, fill=WHITE, outline=BLACK, stroke=2)
        self.set_point_label = Label("""self.font"""terminalio.FONT, x=int(BUTTON_MARGIN + BUTTON_WIDTH*1.5 - 5), 
                                                y=10 + BUTTON_HEIGHT//2 + 1 * BUTTON_MARGIN, 
                                                text="", color=ORANGE)

        self.off_button = self.add_button(0, 0, "ON", color=GREEN)
        self.add_button(1, 0, "UP")
        self.add_button(1, 1, "DOWN")

        for b in self.buttons:
            self.group.append(b)

        #self.group.append(box_border)
        #self.group.append(box_display)
        self.group.append(self.temp_rh_display)
        self.group.append(self.cpu_temp_display)
        self.group.append(self.time_display)
        self.group.append(self.rpm_display)
        self.group.append(set_point_box)
        self.group.append(self.set_point_label)
        self.group.append(mid_line)
        self.group.append(self.set_temp_display)
        self.group.append(self.set_hi_temp_display)

        self.point = None

# Some button functions
    def button_grid(self, row, col):
        return Coords(BUTTON_MARGIN * (col + 1) + BUTTON_WIDTH * col + 0,
                      BUTTON_MARGIN * (row + 1) + BUTTON_HEIGHT * row + 10)

# row/col definition backwards?
    def add_button(self, row, col, label, width=1, color=WHITE, text_color=BLACK):
        pos = self.button_grid(row, col)
        new_button = Button(x=pos.x, y=pos.y,
                            width=BUTTON_WIDTH * width + BUTTON_MARGIN * (width - 1),
                            height=BUTTON_HEIGHT, label=label, label_font=terminalio.FONT"""self.font""",
                            label_color=text_color, fill_color=color, style=Button.ROUNDRECT, label_scale=1)
        self.buttons.append(new_button)
        return new_button

    async def get_touch(self):

        self.touch_logger.info(f'Touch loop started.')
        loop_count = 0
        while True:

# Not sure what ft.touches does...   This seems to work.
            if self.point is not None:
                if self.ft.touches == []:
                    self.point = None

            if self.ft.touched and self.point is None:
                if self.ft.touches != []:
                    self.disable_blink_count = 30
                    self.lite.duty_cycle = 65535
                    try:
                        self.point = (self.ft.touches[0]['x'], self.ft.touches[0]['y'])
                        self.touch_logger.debug(f'Touch detected: {self.point}')
                    except Exception as e:
                        self.touch_logger.error (f'Exception - {e}')

            loop_count += 1
            if self.self_test and loop_count == 5:
                self.point = (self.button_grid(0,0))   # simulates touching on button

            for _, b in enumerate(self.buttons):
                if b.contains(self.point):
                    b.selected = True
                    button = b.label
            
                    if button == "OFF" or button == "ON":
                        b.label = ""

                    time.sleep(0.3)  #don't release the thread
                    b.selected = False

                    if button == "OFF":
                        b.label = "ON"
                        b.fill_color = GREEN
                        ac_base.ac_enable = False
                        self.set_point_label.text = ""
                    if button == "ON":
                        b.label = "OFF"
                        b.fill_color = RED
                        ac_base.ac_enable = True
                        self.set_point_label.text = str(self.temp_set_point)

                    if button == "DOWN" and ac_base.ac_enable:
                        if ac_base.temp_set_point > ac_base.MIN_TEMP:
                            ac_base.temp_set_point -= 1
                        self.set_point_label.text = str(ac_base.temp_set_point)
                        self.gen_temps_plot(False)

                    if button == "UP" and ac_base.ac_enable:
                        if ac_base.temp_set_point < ac_base.MAX_TEMP:
                            ac_base.temp_set_point += 1
                        self.set_point_label.text = str(ac_base.temp_set_point)
                        self.gen_temps_plot(False)

            await asyncio.sleep(0.1)

    async def lite_loop(self):
        
        self.lite_logger.info(f'Starting lite loop:')
        while True:
            self.temp_rh_display.text = f'TEMP:{self.temp:.1f}F ERR:{ac_base.temp_err:.2f} RH:{self.rh:.1f}%'
            self.cpu_temp_display.text = f'CPU: {self.cpu_temp:.1f}F'
            self.time_display.text = f'{self.get_nice_time()}'
            self.rpm_display.text = f'RPM: COMP-{ac_base.compressor_rpm} '+\
                                    f'FAN0-{ac_base.fan_rpm[0]} FAN1-{ac_base.fan_rpm[1]}'

            if self.disable_blink_count != 0:
                self.disable_blink_count -= 1
            else:
                self.lite.duty_cycle = 10000
            await asyncio.sleep(2)
            self.lite.duty_cycle = 65535
            await asyncio.sleep(0.2)

    def gen_temps_plot(self, inc_temps_index):
        max_temp = ac_base.temp
        min_temp = ac_base.temp
        for ii in range(0,ac_base.TEMPS_X_SIZE):
            index = (ac_base.temps_index + ii) % ac_base.TEMPS_X_SIZE
            max_temp = max(max_temp, ac_base.temps_line[index]) if ac_base.temps_line[index] is not None else max_temp
            min_temp = min(min_temp, ac_base.temps_line[index]) if ac_base.temps_line[index] is not None else min_temp
        
        midtemp = (min_temp + max_temp) /2

        temps_extent = max_temp - min_temp
        if temps_extent > 0:
            dots_per_degree = min(TEMPS_Y_EXTENT / temps_extent, 100)
        else:
            dots_per_degree = 0

        bitmaptools.fill_region(self.temps_bitmap, 0, 0, ac_base.TEMPS_X_SIZE, ac_base.TEMPS_Y_SIZE, 0)

        for ii in range(0 , ac_base.TEMPS_X_SIZE-1):
            index = (ac_base.temps_index - ii)  if ac_base.temps_index >= ii else 239 - ii + ac_base.temps_index
            reverse_x_index = (ac_base.TEMPS_X_SIZE - 1) - ii
            y_point = ac_base.temps_line[index]

            if y_point is not None and min_temp is not None:
                y_scaled = ac_base.TEMPS_Y_SIZE//2 - 1  - int((y_point - midtemp) * dots_per_degree) + 1
                if y_scaled < 1 or y_scaled > 105 :
                    print (y_scaled)
                else:
                    self.temps_bitmap[reverse_x_index, y_scaled] = 1
                    self.temps_bitmap[reverse_x_index, y_scaled+1] = 1
                    self.temps_bitmap[reverse_x_index, y_scaled-1] = 1
        
        self.set_temp_display.text = f'{midtemp:.2f}'
        self.set_hi_temp_display.text = f'{max_temp:.2f}'

        if inc_temps_index:
            ac_base.temps_index = (ac_base.temps_index + 1) % ac_base.TEMPS_X_SIZE

if __name__ == "__main__":
    import busio
        
    i2c = busio.I2C(board.SCL, board.SDA) 
    disp = ac_display(i2c)

    while True:
        disp.get_touch()
 