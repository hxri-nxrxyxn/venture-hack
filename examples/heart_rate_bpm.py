"""
Heart Rate (BPM) Estimation Example
Calculates beats per minute (BPM) using a moving-average filter and dynamic threshold peak detector.
Compatible with both MAX30100 (Part ID: 0x11) and MAX30102 (Part ID: 0x15).
"""
import sys
import time
from machine import Pin, SoftI2C

class HeartRateMonitor:
    """Moving-window filter and peak detector for optical PPG signals."""
    def __init__(self, sample_rate=50, window_size=100, smoothing_window=5):
        self.sample_rate = sample_rate
        self.window_size = window_size
        self.smoothing_window = smoothing_window
        self.samples = []
        self.timestamps = []
        self.filtered = []

    def add_sample(self, sample):
        now = time.ticks_ms()
        self.samples.append(sample)
        self.timestamps.append(now)

        # Smooth signal
        if len(self.samples) >= self.smoothing_window:
            smoothed = sum(self.samples[-self.smoothing_window:]) / self.smoothing_window
            self.filtered.append(smoothed)
        else:
            self.filtered.append(sample)

        # Prune old samples
        if len(self.samples) > self.window_size:
            self.samples.pop(0)
            self.timestamps.pop(0)
            self.filtered.pop(0)

    def find_peaks(self):
        peaks = []
        if len(self.filtered) < 5:
            return peaks
        win = self.filtered[-self.window_size:]
        mn, mx = min(win), max(win)
        thresh = mn + (mx - mn) * 0.55

        for i in range(1, len(self.filtered) - 1):
            if (self.filtered[i] > thresh and
                self.filtered[i] > self.filtered[i-1] and
                self.filtered[i] > self.filtered[i+1]):
                peaks.append((self.timestamps[i], self.filtered[i]))
        return peaks

    def calculate_bpm(self):
        peaks = self.find_peaks()
        if len(peaks) < 2:
            return None
        intervals = []
        for i in range(1, len(peaks)):
            dt = time.ticks_diff(peaks[i][0], peaks[i-1][0])
            if 300 <= dt <= 2000:  # Valid beat interval: 30 to 200 BPM
                intervals.append(dt)
        if not intervals:
            return None
        avg_dt = sum(intervals) / len(intervals)
        return 60000 / avg_dt

def get_i2c_pins():
    """Auto-detect default I2C pins based on platform."""
    if sys.platform == "esp8266":
        return 4, 5    # SDA = Pin 4 (D2), SCL = Pin 5 (D1)
    elif sys.platform == "esp32":
        return 21, 22  # SDA = Pin 21, SCL = Pin 22
    elif sys.platform == "rp2":
        return 16, 17  # SDA = Pin 16, SCL = Pin 17
    return 4, 5

def main():
    sda_num, scl_num = get_i2c_pins()
    print(f"Platform: {sys.platform} | SDA=Pin({sda_num}), SCL=Pin({scl_num})")

    i2c = SoftI2C(
        sda=Pin(sda_num, Pin.IN, Pin.PULL_UP),
        scl=Pin(scl_num, Pin.IN, Pin.PULL_UP),
        freq=100000
    )

    devices = i2c.scan()
    if 0x57 not in devices:
        print("[!] Sensor not detected on I2C bus at 0x57.")
        return

    part_id = i2c.readfrom_mem(0x57, 0xFF, 1)[0]
    hr_monitor = HeartRateMonitor(sample_rate=50, window_size=100)
    ref_time = time.ticks_ms()

    if part_id == 0x11:
        print("Detected Sensor: MAX30100 (Part ID: 0x11)")
        from max30100 import MAX30100
        sensor = MAX30100(i2c=i2c)
        sensor.setup(sample_rate=100, pulse_width=1600, red_current=0x07, ir_current=0x07)
        print("Place your finger gently over the sensor. Calculating BPM every 2 seconds...")

        while True:
            samples = sensor.read_sensor()
            for ir, red in samples:
                hr_monitor.add_sample(ir)

            if time.ticks_diff(time.ticks_ms(), ref_time) > 2000:
                bpm = hr_monitor.calculate_bpm()
                if bpm is not None:
                    print("Heart Rate: {:.0f} BPM".format(bpm))
                else:
                    last_val = hr_monitor.samples[-1] if hr_monitor.samples else 0
                    if last_val < 5000:
                        print("Waiting for finger... (IR raw: {})".format(last_val))
                    else:
                        print("Detecting pulse... (IR raw: {})".format(last_val))
                ref_time = time.ticks_ms()
            time.sleep_ms(20)

    elif part_id == 0x15:
        print("Detected Sensor: MAX30102 (Part ID: 0x15)")
        from max30102 import MAX30102, MAX30105_PULSE_AMP_MEDIUM
        sensor = MAX30102(i2c=i2c)
        sensor.setup_sensor()
        sensor.set_sample_rate(400)
        sensor.set_fifo_average(8)
        sensor.set_active_leds_amplitude(MAX30105_PULSE_AMP_MEDIUM)
        print("Place your finger gently over the sensor. Calculating BPM every 2 seconds...")

        while True:
            sensor.check()
            while sensor.available():
                red = sensor.pop_red_from_storage()
                ir = sensor.pop_ir_from_storage()
                hr_monitor.add_sample(ir)

            if time.ticks_diff(time.ticks_ms(), ref_time) > 2000:
                bpm = hr_monitor.calculate_bpm()
                if bpm is not None:
                    print("Heart Rate: {:.0f} BPM".format(bpm))
                else:
                    print("Detecting pulse...")
                ref_time = time.ticks_ms()
            time.sleep_ms(20)

if __name__ == "__main__":
    main()
