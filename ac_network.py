""" Adafruit get_radio_socketpool is just a specialized verion of adafruit_connection_manager.
    Request through adafruit_connect_manager will generate RuntimeError.   Investigation reveals
    this happens when the request discovers the socket in an unexpected state.  Don't know
    why the socket is in these unexpected states.   This socket state is down in the W5500.
    Don't know why the W5500 is in an unexpected state.   Sometimes it fails with a no
    data sent message.
"""

from ac_base import ac_base
from ac_base import CustomStreamHandler
import board #type: ignore
import digitalio #type: ignore
import asyncio
from adafruit_wiznet5k.adafruit_wiznet5k import WIZNET5K #type: ignore
import adafruit_requests #type: ignore
import adafruit_connection_manager #type: ignore
import adafruit_logging as logging #type: ignore
import adafruit_ntp #type: ignore
import time
from cedargrove_dst_adjuster import adjust_dst #type: ignore
import math
from ac_modbus import ac_modbus
from lib.umodbus import modbus

NTP_SERVER_IPADDR = "192.168.1.1"
POST_TEMP_URL = "http://192.168.1.55/cgi-bin/record_ac_temp.py"
POST_POW_URL = "http://192.168.1.55/cgi-bin/record_ac_pow.py"
FAIL_WAIT = 5
NTP_PERIOD = 60
POST_PERIOD = 60

# Doing it without DHCP
IP_ADDRESS = (192, 168, 1, 169)
SUBNET_MASK = (255, 255, 255, 0)
GATEWAY_ADDRESS = (192, 168, 1, 1)
DNS_SERVER = (192, 168, 1, 1)

class ac_network(ac_base):
    def __init__(self):
        super().__init__()

        self.logger = logging.getLogger(__name__)
        self.logger.addHandler(CustomStreamHandler())
        self.logger.setLevel(logging.INFO)
        self.ntp_logger = logging.getLogger("ntp_logger")
        self.ntp_logger.addHandler(CustomStreamHandler())
        self.ntp_logger.setLevel(logging.DEBUG)
        self.post_logger = logging.getLogger("post_logger")
        self.post_logger.addHandler(CustomStreamHandler())
        self.post_logger.setLevel(logging.INFO)
        self.pow_logger = logging.getLogger("pow_logger")
        self.pow_logger.addHandler(CustomStreamHandler())
        self.pow_logger.setLevel(logging.INFO)

        self.ethernet = False
        self.eth_cs = digitalio.DigitalInOut(board.D10)
        self.inits = {"ntp": 0, "post": 0}
        self.successes = {"ntp": 0, "post": 0}
        self.attempts = {"ntp": 0, "post": 0}
        self.init_eth(None)

    def init_eth(self, trans_type):
        self.ethernet = False

        if trans_type is not None:
            self.inits[trans_type] += 1
            self.logger.debug(f'{trans_type}_inits: {self.inits[trans_type]}  {trans_type}_successes: {self.successes[trans_type]}')

        while not self.ethernet:
            try:
                self.eth = WIZNET5K(board.SPI(), self.eth_cs, is_dhcp=False, spi_baudrate=26666666)
                self.eth.ifconfig = (IP_ADDRESS, SUBNET_MASK, GATEWAY_ADDRESS, DNS_SERVER)
                self.ethernet = True
                self.logger.info(f'WIZNET5K initialized.')
            except Exception as e:
                self.logger.error(f'WIZNET5K instantiation failed: {e}')
                continue
        
            self.eth.auto_reconnect = True
            self.eth._debug = False
            self.pool = adafruit_connection_manager.get_radio_socketpool(self.eth) 
            ssl_context = adafruit_connection_manager.get_radio_ssl_context(self.eth)
            self.requests = adafruit_requests.Session(self.pool, ssl_context)


    async def fetch_ntp(self):
        while True:
            self.ntp_logger.debug(f'eth: {self.ethernet} ntp_reads: {self.successes["ntp"]} inits: {self.inits["ntp"]}')
            while not self.ethernet:
                self.init_eth("ntp")
                if not self.ethernet : await asyncio.sleep(FAIL_WAIT)

            while ac_base.time_time is None or (time.time() - ac_base.time_time >= NTP_PERIOD):
                try:
                    self.attempts["ntp"] += 1
                    timestamp_utc_seconds = adafruit_ntp.NTP(self.pool, server=NTP_SERVER_IPADDR).utc_ns//int(1e+9)
                    mst_seconds = timestamp_utc_seconds - 7 * 60 * 60
                    adjusted_xst, is_dst = adjust_dst(time.localtime(mst_seconds))
                    ac_base.xst_seconds = mst_seconds+60*60 if is_dst else mst_seconds
                    self.ntp_logger.debug (f'ntp xst: {time.localtime(ac_base.xst_seconds)}')
                    # seconds from 1/1/1970 till 1/1/2000.   time.time() initialized at poweron.   Not reset with soft reset.
                    ac_base.time_time = time.time()
                    self.successes["ntp"] += 1
                    continue
                except RuntimeError as e: 
                    self.ntp_logger.error(f'RuntimeError fetching ntp: {e}')
                except Exception as e:
                    self.ntp_logger.error(f'Exception fetching ntp: {e}')
                await asyncio.sleep(FAIL_WAIT)
                self.init_eth("ntp")
            await asyncio.sleep(NTP_PERIOD)
        
    async def post_temp(self):
        while True:
            self.post_logger.debug(f'eth: {self.ethernet} posts: {self.successes["post"]} inits: {self.inits["post"]}')
            while math.isnan(ac_base.temp): await asyncio.sleep(FAIL_WAIT)

            while not self.ethernet:
                self.init_eth("post")
                if not self.ethernet : await asyncio.sleep(FAIL_WAIT)

            while True:
                self.attempts["post"] += 1
                post_temp_data = f'{{"time":{self.get_localtime()}, "temp":{ac_base.temp:.1f}}}'
                try:
                    with self.requests.post(POST_TEMP_URL, data=post_temp_data) as response:
                        if response.status_code != 200:
                            self.post_logger.error (f'Non 200 status , {response.status_code}')
                            self.post_logger.error(f'headers , {response.headers}')
                        else: 
                            self.successes["post"] += 1
                            self.post_logger.debug(f'Post response test: {response.text}')
                            await asyncio.sleep(POST_PERIOD)
                            continue
                except RuntimeError as e: 
                    self.post_logger.error (f'RuntimeError: {e}')
                except adafruit_requests.OutOfRetries as e: 
                    self.post_logger.error (f'adafruit_requests.OutOfRetries: {e}')
                except Exception as e: 
                    self.post_logger.error(f'Ethernet post error: {e}')
                await asyncio.sleep(FAIL_WAIT)
                self.init_eth("post")

    async def post_pow(self):
        while True:
            self.pow_logger.debug(f'eth: {self.ethernet} posts: {self.successes["post"]} inits: {self.inits["post"]}')
            while math.isnan(ac_base.temp): await asyncio.sleep(FAIL_WAIT)

            while not self.ethernet:
                self.init_eth("post")
                if not self.ethernet : await asyncio.sleep(FAIL_WAIT)

            while True:
                self.attempts["post"] += 1
                post_pow_data = f'{{"time":{self.get_localtime()}, "pow":{ac_base.compressor_pow:.1f}}}'
                try:
                    with self.requests.post(POST_POW_URL, data=post_pow_data) as response:
                        if response.status_code != 200:
                            self.pow_logger.error (f'Non 200 status , {response.status_code}')
                            self.pow_logger.error(f'headers , {response.headers}')
                        else: 
                            self.successes["post"] += 1
                            self.pow_logger.debug(f'Post response test: {response.text}')
                            await asyncio.sleep(POST_PERIOD)
                            continue
                except RuntimeError as e: 
                    self.pow_logger.error (f'RuntimeError: {e}')
                except adafruit_requests.OutOfRetries as e: 
                    self.pow_logger.error (f'adafruit_requests.OutOfRetries: {e}')
                except Exception as e: 
                    self.pow_logger.error(f'Ethernet post error: {e}')
                await asyncio.sleep(FAIL_WAIT)
                self.init_eth("post")

                


            

        
