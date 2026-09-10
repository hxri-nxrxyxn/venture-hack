"""
Leaf Optical Health & Chlorophyll (NDVI) Analyzer - MAX30102 Edition
Measures Red (660nm) and Near-Infrared (880nm) optical reflectance/transmittance
to estimate chlorophyll content, vegetation indices (NDVI & RVI), and plant leaf health.

Dedicated for MAX30102 (Part ID: 0x15).
Supports ESP8266, ESP32, and RP2040 microcontrollers.
"""
import sys
import time
import math
import gc
from machine import Pin, SoftI2C
from max30102 import MAX30102, MAX30105_PULSE_AMP_LOW, MAX30105_PULSE_AMP_MEDIUM

# ── Configuration ─────────────────────────────────────────────────────────────
# Optical normalization factor (ratio of IR to RED sensitivity on white reference)
DEFAULT_WHITE_RED = 150000.0
DEFAULT_WHITE_IR  = 150000.0

# Reporting interval in milliseconds
REPORT_INTERVAL_MS = 1500


def get_i2c_pins():
    """Auto-detect default I2C pins based on platform."""
    if sys.platform == "esp8266":
        return 4, 5    # SDA = Pin 4 (D2), SCL = Pin 5 (D1)
    elif sys.platform == "esp32":
        return 21, 22  # SDA = Pin 21, SCL = Pin 22
    elif sys.platform == "rp2":
        return 16, 17  # SDA = Pin 16, SCL = Pin 17
    return 4, 5


def classify_leaf_health(ndvi, rvi):
    """
    Classify plant leaf health based on NDVI (Normalized Difference Vegetation Index)
    and RVI (Ratio Vegetation Index = NIR / RED).
    """
    if ndvi >= 0.45:
        return "Healthy (High Chlorophyll)"
    elif ndvi >= 0.25:
        return "Moderate (Mild Stress / Maturing)"
    elif ndvi >= 0.08:
        return "Chlorotic (Yellowing / Nutrient Deficiency)"
    else:
        return "Necrotic / Senescent (Dry / Dead Tissue)"


def main():
    sda_num, scl_num = get_i2c_pins()
    print(f"Platform: {sys.platform} | SDA=Pin({sda_num}), SCL=Pin({scl_num})")

    i2c = SoftI2C(
        sda=Pin(sda_num, Pin.IN, Pin.PULL_UP),
        scl=Pin(scl_num, Pin.IN, Pin.PULL_UP),
        freq=100000
    )
    time.sleep_ms(100)

    devices = []
    for _ in range(5):
        devices = i2c.scan()
        if 0x57 in devices:
            break
        time.sleep_ms(50)

    if 0x57 not in devices:
        print("[!] Sensor address 0x57 not detected on I2C bus.")
        return

    part_id = i2c.readfrom_mem(0x57, 0xFF, 1)[0]
    rev_id = i2c.readfrom_mem(0x57, 0xFE, 1)[0]

    if part_id == 0x11:
        print(f"[!] Detected MAX30100 (Part ID: 0x11, Rev ID: {hex(rev_id)}).")
        print("    This script is specifically configured for MAX30102 (Part ID: 0x15).")
        print("    Please use 'examples/leaf_health_ndvi.py' for MAX30100 compatibility.")
        return
    elif part_id != 0x15:
        print(f"[!] Unknown sensor at 0x57 (Part ID: {hex(part_id)})")
        return

    print(f"Detected Sensor: MAX30102 (Part ID: 0x15, Rev ID: {hex(rev_id)})")

    # Initialize MAX30102
    sensor = MAX30102(i2c=i2c)
    sensor.setup_sensor()
    # 200 Hz sampling with 4x FIFO averaging -> 50 effective samples/sec
    sensor.set_sample_rate(200)
    sensor.set_fifo_average(4)
    # LOW pulse amplitude (~6.4mA) prevents photodiode saturation on reflective leaf surfaces
    sensor.set_active_leds_amplitude(MAX30105_PULSE_AMP_LOW)

    try:
        temp = sensor.read_temperature()
        print(f"Sensor Die Temperature: {temp:.1f} °C")
    except:
        temp = None

    print("================================================================")
    print(" MAX30102 Leaf Health & Chlorophyll Analyzer Online")
    print("----------------------------------------------------------------")
    print(" Instructions:")
    print(" 1. Press leaf blade flat against the sensor (avoid main stem).")
    print(" 2. Shield sensor from external room light/sunlight for accuracy.")
    print("================================================================\n")

    ir_acc = 0
    red_acc = 0
    count = 0
    ref_time = time.ticks_ms()

    while True:
        sensor.check()
        while sensor.available():
            red = sensor.pop_red_from_storage()
            ir = sensor.pop_ir_from_storage()
            ir_acc += ir
            red_acc += red
            count += 1

        now = time.ticks_ms()
        if time.ticks_diff(now, ref_time) >= REPORT_INTERVAL_MS and count > 0:
            avg_ir = ir_acc / count
            avg_red = red_acc / count

            # Reset accumulators for next interval
            ir_acc = 0
            red_acc = 0
            count = 0
            ref_time = now

            # Check for 18-bit ADC optical saturation (> 255,000 counts)
            if avg_ir > 255000 or avg_red > 255000:
                print(f"[LEAF DUMP] IR: {int(avg_ir):6d} | RED: {int(avg_red):6d} | [!] Optical saturation - reduce LED power")
                continue

            # Check for minimum signal (leaf present vs empty / dark)
            if avg_ir < 1000 and avg_red < 1000:
                print(f"[LEAF DUMP] IR: {int(avg_ir):6d} | RED: {int(avg_red):6d} | Waiting for leaf sample...")
                continue

            # Normalized reflectance
            norm_ir = avg_ir / DEFAULT_WHITE_IR
            norm_red = avg_red / DEFAULT_WHITE_RED

            # Calculate NDVI = (NIR - RED) / (NIR + RED)
            denom = norm_ir + norm_red
            if denom > 0:
                ndvi = (norm_ir - norm_red) / denom
            else:
                ndvi = 0.0

            # Clamp NDVI to valid theoretical bounds [-1.0, +1.0]
            ndvi = max(-1.0, min(1.0, ndvi))

            # Calculate RVI (Ratio Vegetation Index = NIR / RED)
            rvi = (norm_ir / norm_red) if norm_red > 0.001 else 99.9

            # Estimate relative chlorophyll index (log ratio SPAD equivalent)
            try:
                spad_est = round(10.0 * math.log(rvi), 1) if rvi > 0 else 0.0
            except:
                spad_est = 0.0

            status = classify_leaf_health(ndvi, rvi)
            print(f"[LEAF DUMP] IR: {int(avg_ir):6d} | RED: {int(avg_red):6d} | NDVI: {ndvi:+.3f} | RVI: {rvi:4.2f} | SPAD~: {spad_est:4.1f} | {status}")
            gc.collect()

        time.sleep_ms(20)


if __name__ == "__main__":
    main()
