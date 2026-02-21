from ac_base import ac_base
from ac_base import CustomStreamHandler 
import adafruit_24lc32
import adafruit_logging as logging
import os
import adafruit_hashlib as hashlib

NV_CAPACITY = 4096
HASH_LENGTH = 32
HASH_SPOT = NV_CAPACITY - HASH_LENGTH
    
MAP = {"auto_on": (0, 1),
       "set_point": (1, 2),
       "md5": (HASH_SPOT, NV_CAPACITY)}

class AcNonVolatile(ac_base):

    def __init__(self, i2c):

        try:
            self.nv = adafruit_24lc32.EEPROM_I2C(i2c)
            self.nv_logger.info(f"EEPROM found.")  
        except Exception as e:
            self.nv_logger.error(f"Failed to initialize EEPROM: {e}")  
            self.nv = None
        

    def read_nv(self, label):
        self.nv_logger.debug(f"Read NV for label {label}.")
        if self.nv is None:
            return None
        if self.check_hash() == False:
            return False
        idx0, idx1 = self.get_index(label)
        return(self.fetch_nv(idx0, idx1))

    def write_nv(self, label, data):
        self.nv_logger.debug(f"Writing {data[0]} to {label}.") 
        if self.nv is None:
            return None
        idx0, idx1 = self.get_index(label)
        if idx1 - idx0 < len(data):
            self.nv_logger.error(f'Data length {len(data)} exceeds allocated space {idx1-idx0} for label {label}.')
            return False
        if self.post_nv(idx0, idx1, data) == False:
            self.nv_logger.error(f'Failed to write {data} to label {label}.')
            return False
        idx0, idx1 = self.get_index("md5")
        if self.post_nv(idx0, idx1, self.compute_hash()) == False:
            self.nv_logger.error(f'Failed to update hash after writing {data} to label {label}.')
            return False 
        return True

    def get_index(self, label):
        if label in MAP:
            idx0 = MAP[label][0]
            idx1 = MAP[label][1]
            return idx0, idx1
        else:
            # Program error.  Fatal.   But post a hint.
            self.nv_logger.critical(f'label: {label} not in MAP.')
            return None, None
       
    def compute_hash(self):
        hash = hashlib.md5()
        for ii in MAP:
            idx0, idx1 = self.get_index(ii)
            if ii != "md5":
                self.nv_logger.debug(f'Adding label {ii} data {int.from_bytes(self.fetch_nv(idx0, idx1), "big")} to hash.')
                data = self.fetch_nv(idx0, idx1)
                if data == False:
                    return False
                hash.update(data)
        self.nv_logger.debug(f'hash.hexdigest {hash.hexdigest()})')
        return hash.hexdigest().encode('utf-8')
    
    def check_hash(self):
        idx0, idx1 = self.get_index("md5")
        stored_hash = self.fetch_nv(idx0, idx1)
        computed_hash = self.compute_hash()
        if stored_hash != computed_hash or not stored_hash or not computed_hash:
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

