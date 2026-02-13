from ac_base import ac_base
from ac_base import CustomStreamHandler 
import adafruit_24lc32
import adafruit_logging as logging
import os
import adafruit_hashlib as hashlib

I2C_24LC32 = os.getenv("I2C_24LC32", 80)

NV_CAPACITY = 4096
HASH_LENGTH = 32
HASH_SPOT = NV_CAPACITY - HASH_LENGTH
    

MAP = {"auto_on": (0, 1),
       "set_point": (1, 2),
       "md5": (HASH_SPOT, NV_CAPACITY)}

class ac_non_volatile(ac_base):

    def __init__(self, i2c, logger):
        self.nv_logger = logger

        try:
            self.nv = adafruit_24lc32.EEPROM_I2C(i2c)
        except Exception as e:
            self.nv_logger.error(f"Failed to initialize EEPROM: {e}")  
            self.nv = None

    def read_nv(self, label):
        self.nv_logger.debug(f"Attempting to read NV for label {label}.")
        if self.nv is None:
            return None
        if self.check_hash() == False:
            return None
        idx0, idx1, length = self.get_index(label)
        self.nv_logger.debug(f'{idx0} {idx1}')
        return(self.fetch_nv(idx0, idx1))

    def write_nv(self, label, data):
        if self.nv is None:
            return None
        idx0, idx1, length = self.get_index(label)
        if length < len(data):
            self.nv_logger.error(f'Data length {len(data)} exceeds allocated space {length} for label {label}.')
            return False
        if self.post_nv(idx0, idx1, data) == False:
            self.nv_logger.error(f'Failed to write {data} to label {label}.')
            return False
        """if label == "set_point":
            idx0, idx1, length = self.get_index("auto_on")
            if self.post_nv(idx0, idx1, b'\X00') == False:
                self.logger.error(f'Failed to set auto_on flag for set_point update.')
                return False"""
        idx0, idx1, length = self.get_index("md5")
        if self.post_nv(idx0, idx1, self.compute_hash()) == False:
            self.nv_logger.error(f'Failed to update hash after writing {data} to label {label}.')
            return False 
        return True

    def get_index(self, label):
        idx0 = MAP[label][0]
        idx1 = MAP[label][1]
        self.nv_logger.debug(f'get_index for {label} returns {idx0}, {idx1}, length {idx1-idx0}')    
        return idx0, idx1, idx1-idx0
       
    def compute_hash(self):
        hash = hashlib.md5()
        for ii in MAP:
            idx0, idx1, length = self.get_index(ii)
            if ii != "md5":
                self.nv_logger.debug(f'Hashing label {ii} data {self.fetch_nv(idx0, idx1)}')
                data = self.fetch_nv(idx0, idx1)
                if data == False:
                    return False
                hash.update(data)
        self.nv_logger.debug(f'hash.hexdigest {hash.hexdigest()})')
        return hash.hexdigest().encode('utf-8')
    
    def check_hash(self):
        idx0, idx1, length = self.get_index("md5")
        stored_hash = self.fetch_nv(idx0, idx1)
        computed_hash = self.compute_hash()
        if stored_hash != computed_hash and stored_hash and computed_hash:
            self.nv_logger.error(f'Hash mismatch: stored {stored_hash} computed {computed_hash}.')           
            return False
        return True
    
    def fetch_nv(self, idx0, idx1):
        try:
            data = self.nv[idx0:idx1]  
            return data
        except Exception as e:
            self.nv_logger.error(f"Failed to fetch NV data from index {idx0} to {idx1}: {e}")
            return False
        
    def post_nv(self, idx0, idx1, data):
        try:
            self.nv[idx0:idx1] = data
            return True
        except Exception as e:
            self.logger.error(f"Failed to write {data} to NV from index {idx0} to {idx1}: {e}")
            return False

