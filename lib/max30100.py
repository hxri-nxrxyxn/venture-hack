"""
MicroPython MAX30100 Driver
Optimized for ESP8266 & ESP32 with low memory footprint and fault tolerance
"""
from machine import SoftI2C, Pin
import time

MAX30100_I2C_ADDR = 0x57

INT_STATUS   = 0x00
INT_ENABLE   = 0x01
FIFO_WR_PTR  = 0x02
OVR_COUNTER  = 0x03
FIFO_RD_PTR  = 0x04
FIFO_DATA    = 0x05
MODE_CONF    = 0x06
SPO2_CONF    = 0x07
LED_CONF     = 0x09
TEMP_INT     = 0x16
TEMP_FRAC    = 0x17
REV_ID       = 0xFE
PART_ID      = 0xFF

MODE_HR_ONLY = 0x02
MODE_SPO2    = 0x03

class MAX30100:
    def __init__(self, i2c: SoftI2C, address=MAX30100_I2C_ADDR):
        self.i2c = i2c
        self.address = address
        self.part_id = self.read_part_id()
        self.rev_id = self.read_rev_id()

    def read_part_id(self):
        try:
            return self.i2c.readfrom_mem(self.address, PART_ID, 1)[0]
        except:
            return 0

    def read_rev_id(self):
        try:
            return self.i2c.readfrom_mem(self.address, REV_ID, 1)[0]
        except:
            return 0

    def reset(self):
        try:
            self.i2c.writeto_mem(self.address, MODE_CONF, bytearray([0x40]))
            for _ in range(20):
                time.sleep_ms(10)
                if not (self.i2c.readfrom_mem(self.address, MODE_CONF, 1)[0] & 0x40):
                    break
        except:
            pass

    def setup(self, mode=MODE_SPO2, sample_rate=100, pulse_width=1600, red_current=0x07, ir_current=0x07, high_res=True):
        self.reset()
        try:
            # Mode
            self.i2c.writeto_mem(self.address, MODE_CONF, bytearray([mode]))
            # SpO2 & Sample Rate
            sr_map = {50: 0, 100: 1, 167: 2, 200: 3, 400: 4, 600: 5, 800: 6, 1000: 7}
            pw_map = {200: 0, 400: 1, 800: 2, 1600: 3}
            sr_bits = sr_map.get(sample_rate, 1) << 2
            pw_bits = pw_map.get(pulse_width, 3)
            hires_bit = 0x40 if high_res else 0x00
            self.i2c.writeto_mem(self.address, SPO2_CONF, bytearray([hires_bit | sr_bits | pw_bits]))
            # LED Current
            led_val = ((red_current & 0x0F) << 4) | (ir_current & 0x0F)
            self.i2c.writeto_mem(self.address, LED_CONF, bytearray([led_val]))
            self.clear_fifo()
        except:
            pass

    def clear_fifo(self):
        try:
            self.i2c.writeto_mem(self.address, FIFO_WR_PTR, bytearray([0x00]))
            self.i2c.writeto_mem(self.address, OVR_COUNTER, bytearray([0x00]))
            self.i2c.writeto_mem(self.address, FIFO_RD_PTR, bytearray([0x00]))
        except:
            pass

    def read_temperature(self):
        try:
            m = self.i2c.readfrom_mem(self.address, MODE_CONF, 1)[0]
            self.i2c.writeto_mem(self.address, MODE_CONF, bytearray([m | (1 << 3)]))
            for _ in range(50):
                time.sleep_ms(5)
                if not (self.i2c.readfrom_mem(self.address, MODE_CONF, 1)[0] & (1 << 3)):
                    break
            t_int = self.i2c.readfrom_mem(self.address, TEMP_INT, 1)[0]
            if t_int > 127:
                t_int -= 256
            t_frac = self.i2c.readfrom_mem(self.address, TEMP_FRAC, 1)[0]
            return t_int + (t_frac * 0.0625)
        except:
            return 0.0

    def read_sensor(self):
        samples = []
        try:
            w = self.i2c.readfrom_mem(self.address, FIFO_WR_PTR, 1)[0]
            r = self.i2c.readfrom_mem(self.address, FIFO_RD_PTR, 1)[0]
            num_samples = (w - r) & 0x0F
            if num_samples == 0:
                ovr = self.i2c.readfrom_mem(self.address, OVR_COUNTER, 1)[0]
                if ovr > 0:
                    num_samples = 16
            if num_samples > 0:
                b = self.i2c.readfrom_mem(self.address, FIFO_DATA, num_samples * 4)
                for i in range(0, len(b), 4):
                    ir = (b[i] << 8) | b[i+1]
                    red = (b[i+2] << 8) | b[i+3]
                    samples.append((ir, red))
        except OSError:
            pass
        return samples
