import time
import adafruit_logging as logging
import sys
import os

class ac_base():
    SELF_TEST_MODE= os.getenv("SELF_TEST_MODE", "false").lower() == "true"
    MAX_TEMP = int(os.getenv("MAX_TEMP", "75"))
    MIN_TEMP = int(os.getenv("MIN_TEMP", "60"))
    DISPLAY_X_SIZE = 240
    DISPLAY_Y_SIZE = 320
    TEMPS_X_SIZE = DISPLAY_X_SIZE
    TEMPS_Y_SIZE = DISPLAY_Y_SIZE//3 + 1
    temps_line = [None] * TEMPS_X_SIZE
    temps_index = 0
    if SELF_TEST_MODE : temp_set_point = 70
    else: temp_set_point = MAX_TEMP
    ac_enable = False
    temp = float('nan')
    temp_err = float('nan')
    rh = float('nan') 
    cpu_temp = float('nan')
    xst_seconds = None
    time_time = None
    compressor_rpm = None
    fan_rpm = [None, None]
    fan_percent_requested_rpm = [1000, 1000]
    pid_demand = None

    def __init__(self):
        pass

    def get_localtime(self):
        if self.xst_seconds != None and self.time_time != None:
            local_seconds = time.time() - self.time_time
            return(self.xst_seconds + local_seconds)
        else:
            return time.time()
    
    def get_minutes(self):
        xst_time = time.localtime(self.get_localtime())
        return (xst_time.tm_sec)
            
    def get_nice_time(self):
        xst_time = time.localtime(self.get_localtime())
        nice_time = f'{str(xst_time.tm_year)[2:]}-{xst_time.tm_mon}-{xst_time.tm_mday} '
        nice_time += f'{xst_time.tm_hour:02d}:{xst_time.tm_min:02d}:{xst_time.tm_sec:02d}'
        return nice_time


        
class CustomStreamHandler(logging.Handler, ac_base):
    """Send logging output to a stream (sys.stderr by default) with a custom format."""

    def __init__(self, stream=None, level=logging.NOTSET):
        super().__init__(level)
        #ac_base __init__ is a nop
        self.stream = stream if stream is not None else sys.stderr

    def format(self, record):
        """Generate a custom formatted string to log."""
        # The base format includes timestamp, levelname, and message.
        # You can customize the entire string here.
        # record attributes available: name, levelno, levelname, msg
        # The default format is "{timestamp}: {levelname} - {msg}"
        #custom_message = "{}: {} {} - {}".format(record.created, record.name, record.levelname, record.msg)
        custom_message = f'{self.get_nice_time()}: {record.name} {record.levelname} - {record.msg}'
        return custom_message + "\n" # Add newline character

    def emit(self, record):
        """Generate the message and write it to the stream."""
        self.stream.write(self.format(record))
        self.flush()

    def flush(self): 
        """Flush the stream."""
        #self.stream.flush()  # stream.flush doesn't work?? 
        pass