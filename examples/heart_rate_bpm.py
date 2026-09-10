"""
Heart Rate (BPM) Estimation Example
Calculates beats per minute (BPM) using moving-average filtering,
dicrotic notch rejection (65% dynamic threshold + 380ms refractory period),
and median interval smoothing.
Compatible with both MAX30100 (Part ID: 0x11) and MAX30102 (Part ID: 0x15).
"""
import sys
import time
import gc
from machine import Pin, SoftI2C

# Configuration
RAW_STREAM = False  # Set True to stream every sample continuously
REPORT_MS = 2000    # Reporting interval in milliseconds


class HeartRateMonitor:
    """Sliding-window pulse detector with dicrotic notch filter and median smoothing."""
    def __init__(self, window_size=160, smoothing_window=7):
        self.window_size = window_size
        self.smoothing_window = smoothing_window
        self.samples = []
        self.timestamps = []
        self.filtered = []
        self.bpm_history = []
        self.last_bpm = None

    def reset(self):
        self.samples.clear()
        self.timestamps.clear()
        self.filtered.clear()
        self.bpm_history.clear()
        self.last_bpm = None

    def add_sample(self, sample):
        now = time.ticks_ms()
        self.samples.append(sample)
        self.timestamps.append(now)

        # Moving average filter for high-frequency noise suppression
        if len(self.samples) >= self.smoothing_window:
            smoothed = sum(self.samples[-self.smoothing_window:]) // self.smoothing_window
            self.filtered.append(smoothed)
        else:
            self.filtered.append(sample)

        # Maintain window size
        if len(self.samples) > self.window_size:
            del self.samples[:len(self.samples) - self.window_size]
            del self.timestamps[:len(self.timestamps) - self.window_size]
            del self.filtered[:len(self.filtered) - self.window_size]

    def find_peaks(self):
        peaks = []
        n = len(self.filtered)
        if n < 20:
            return peaks

        mn = min(self.filtered)
        mx = max(self.filtered)
        span = mx - mn
        if span < 25:  # Flat / weak AC pulse
            return peaks

        # 65% threshold: rejects the smaller secondary dicrotic notch
        thresh = mn + int(span * 0.65)
        # 380ms refractory period: blocks double-peaks up to 157 BPM
        min_peak_distance_ms = 380

        for i in range(1, n - 1):
            val = self.filtered[i]
            if val > thresh and val > self.filtered[i - 1] and val >= self.filtered[i + 1]:
                t = self.timestamps[i]
                if not peaks:
                    peaks.append((t, val))
                else:
                    if time.ticks_diff(t, peaks[-1][0]) < min_peak_distance_ms:
                        if val > peaks[-1][1]:
                            peaks[-1] = (t, val)
                    else:
                        peaks.append((t, val))
        return peaks

    def calculate_bpm(self):
        peaks = self.find_peaks()
        if len(peaks) < 2:
            return self.last_bpm

        intervals = []
        for i in range(1, len(peaks)):
            dt = time.ticks_diff(peaks[i][0], peaks[i - 1][0])
            # Valid interval range: 380ms (157 BPM) to 1500ms (40 BPM)
            if 380 <= dt <= 1500:
                intervals.append(dt)

        if not intervals:
            return self.last_bpm

        # Median interval to eliminate outlier beats
        intervals.sort()
        med_dt = intervals[len(intervals) // 2]
        raw_bpm = int(round(60000.0 / med_dt))

        if not (40 <= raw_bpm <= 180):
            return self.last_bpm

        self.bpm_history.append(raw_bpm)
        if len(self.bpm_history) > 4:
            self.bpm_history.pop(0)

        # Median over recent reports to produce smooth, non-jumping readings
        s = sorted(self.bpm_history)
        self.last_bpm = s[len(s) // 2]
        return self.last_bpm


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

    devices = []
    for _ in range(5):
        devices = i2c.scan()
        if 0x57 in devices:
            break
        time.sleep_ms(50)

    if 0x57 not in devices:
        print("[!] Sensor not detected on I2C bus at 0x57.")
        return

    part_id = i2c.readfrom_mem(0x57, 0xFF, 1)[0]
    ref_time = time.ticks_ms()
    latest_ir = 0
    latest_red = 0

    if part_id == 0x11:
        print("Detected Sensor: MAX30100 (Part ID: 0x11)")
        from max30100 import MAX30100
        sensor = MAX30100(i2c=i2c)
        sensor.setup(sample_rate=100, pulse_width=411, red_current=0xFF, ir_current=0xFF)
        hr_monitor = HeartRateMonitor(window_size=160, smoothing_window=7)
        print("Sensor initialized. Calculating BPM and outputting raw data every 2 seconds...\n")

        while True:
            samples = sensor.read_sensor()
            if samples:
                for ir, red in samples:
                    hr_monitor.add_sample(ir)
                    latest_ir = ir
                    latest_red = red
                    if RAW_STREAM:
                        print(f"RAW: IR={ir}, RED={red}")

            now = time.ticks_ms()
            if time.ticks_diff(now, ref_time) >= REPORT_MS:
                ref_time = now
                if latest_ir < 5000:
                    status = "Waiting for finger..."
                    hr_monitor.reset()
                else:
                    bpm = hr_monitor.calculate_bpm()
                    if bpm is not None:
                        status = f"Heart Rate: {bpm} BPM"
                    else:
                        status = "Detecting pulse..."

                print(f"[RAW DUMP] IR: {latest_ir:5d} | RED: {latest_red:5d} | {status}")
                gc.collect()

            time.sleep_ms(20)

    elif part_id == 0x15:
        print("Detected Sensor: MAX30102 (Part ID: 0x15)")
        from max30102 import MAX30102, MAX30105_PULSE_AMP_MEDIUM
        sensor = MAX30102(i2c=i2c)
        sensor.setup_sensor()
        sensor.set_sample_rate(400)
        sensor.set_fifo_average(8)
        sensor.set_active_leds_amplitude(MAX30105_PULSE_AMP_MEDIUM)
        hr_monitor = HeartRateMonitor(window_size=100, smoothing_window=5)
        print("Sensor initialized. Calculating BPM and outputting raw data every 2 seconds...\n")

        while True:
            sensor.check()
            while sensor.available():
                red = sensor.pop_red_from_storage()
                ir = sensor.pop_ir_from_storage()
                hr_monitor.add_sample(ir)
                latest_ir = ir
                latest_red = red
                if RAW_STREAM:
                    print(f"RAW: IR={ir}, RED={red}")

            now = time.ticks_ms()
            if time.ticks_diff(now, ref_time) >= REPORT_MS:
                ref_time = now
                if latest_ir < 5000:
                    status = "Waiting for finger..."
                    hr_monitor.reset()
                else:
                    bpm = hr_monitor.calculate_bpm()
                    if bpm is not None:
                        status = f"Heart Rate: {bpm} BPM"
                    else:
                        status = "Detecting pulse..."

                print(f"[RAW DUMP] IR: {latest_ir:5d} | RED: {latest_red:5d} | {status}")
                gc.collect()

            time.sleep_ms(20)

    else:
        print(f"Unknown sensor detected at 0x57 with Part ID: {hex(part_id)}")


if __name__ == "__main__":
    main()
