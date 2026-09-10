"""
Basic Optical Reading Example (RED & IR Channels)
Compatible with both MAX30100 (Part ID: 0x11) and MAX30102 (Part ID: 0x15).
Auto-detects platform pinout for ESP8266, ESP32, and RP2040.
"""
import sys
import time
from machine import Pin, SoftI2C

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

    print("I2C Bus Scan:", [hex(d) for d in devices])

    if 0x57 not in devices:
        print("[!] Sensor address 0x57 not detected on I2C bus.")
        print("    Please check wiring:")
        print("    - VIN -> 3.3V or 5V (VU)")
        print("    - GND -> GND")
        print(f"    - SDA -> GPIO {sda_num}")
        print(f"    - SCL -> GPIO {scl_num}")
        return

    part_id = i2c.readfrom_mem(0x57, 0xFF, 1)[0]
    rev_id = i2c.readfrom_mem(0x57, 0xFE, 1)[0]

    if part_id == 0x11:
        print(f"Detected Sensor: MAX30100 (Part ID: 0x11, Rev ID: {hex(rev_id)})")
        from max30100 import MAX30100
        sensor = MAX30100(i2c=i2c)
        sensor.setup(sample_rate=100, pulse_width=1600, red_current=0x07, ir_current=0x07)
        print("Die Temperature:", round(sensor.read_temperature(), 2), "°C")
        print("\nStreaming IR & RED readings (compatible with Serial Plotter):")
        print("IR, RED")
        while True:
            samples = sensor.read_sensor()
            for ir, red in samples:
                print(f"{ir}, {red}")
            time.sleep_ms(20)

    elif part_id == 0x15:
        print(f"Detected Sensor: MAX30102 (Part ID: 0x15, Rev ID: {hex(rev_id)})")
        from max30102 import MAX30102, MAX30105_PULSE_AMP_MEDIUM
        sensor = MAX30102(i2c=i2c)
        sensor.setup_sensor()
        sensor.set_sample_rate(400)
        sensor.set_fifo_average(8)
        sensor.set_active_leds_amplitude(MAX30105_PULSE_AMP_MEDIUM)
        print("Die Temperature:", round(sensor.read_temperature(), 2), "°C")
        print("\nStreaming RED & IR readings (compatible with Serial Plotter):")
        print("RED, IR")
        while True:
            sensor.check()
            while sensor.available():
                red = sensor.pop_red_from_storage()
                ir = sensor.pop_ir_from_storage()
                print(f"{red}, {ir}")
            time.sleep_ms(20)
    else:
        print(f"Unknown sensor detected at 0x57 with Part ID: {hex(part_id)}")

if __name__ == "__main__":
    main()
