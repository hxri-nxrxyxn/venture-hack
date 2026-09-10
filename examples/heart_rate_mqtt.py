"""
Heart Rate (BPM) & Sensor Streamer over Secure MQTT (TLS)
Streams BPM, IR, RED, and status to HiveMQ Cloud over TLS (Port 8883).
Compatible with both MAX30100 (Part ID: 0x11) and MAX30102 (Part ID: 0x15).
"""
import sys
import time
import gc
import ujson
import network
from machine import Pin, SoftI2C
from umqtt.simple import MQTTClient

# ==============================================================================
# CONFIGURATION
# ==============================================================================
# WiFi Credentials
WIFI_SSID = "DESKTOP-Daisu"
WIFI_PASSWORD = "hlothisisme:)"

# HiveMQ Cloud Broker Settings
MQTT_BROKER = "99db9c66011f4f0d955e8e8b8fade3cd.s1.eu.hivemq.cloud"
MQTT_PORT = 8883
MQTT_CLIENT_ID = "esp_sensor_client"
MQTT_USER = "hakku04"
MQTT_PASSWORD = "Hari@2004"
MQTT_TOPIC = b"esptool/sensor/data"       # Topic published to

# Sensor Reporting Interval
REPORT_MS = 2000    # Interval to publish MQTT telemetry (milliseconds)
RAW_STREAM = False  # Set True to print every sample to local serial
# ==============================================================================


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

        thresh = mn + int(span * 0.65)
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
            if 380 <= dt <= 1500:
                intervals.append(dt)

        if not intervals:
            return self.last_bpm

        intervals.sort()
        med_dt = intervals[len(intervals) // 2]
        raw_bpm = int(round(60000.0 / med_dt))

        if not (40 <= raw_bpm <= 180):
            return self.last_bpm

        self.bpm_history.append(raw_bpm)
        if len(self.bpm_history) > 4:
            self.bpm_history.pop(0)

        s = sorted(self.bpm_history)
        self.last_bpm = s[len(s) // 2]
        return self.last_bpm


def connect_wifi():
    """Connect to local WiFi access point."""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print(f"Connecting to WiFi '{WIFI_SSID}'...")
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        timeout = 25
        while not wlan.isconnected() and timeout > 0:
            time.sleep(1)
            timeout -= 1
            print(".", end="")
        print()

    if wlan.isconnected():
        print(f"WiFi Connected! IP: {wlan.ifconfig()[0]}")
        return True
    else:
        print("[!] Failed to connect to WiFi.")
        return False


HIVEMQ_CLUSTER_IPS = ["54.73.92.158", "52.31.149.80", "46.137.47.218"]


def connect_mqtt():
    """Establish a TLS-secured MQTT connection to HiveMQ Cloud."""
    import socket
    target_host = MQTT_BROKER
    try:
        socket.getaddrinfo(MQTT_BROKER, MQTT_PORT)
    except Exception:
        # Fallback to direct cluster IPs if local network DNS query is blocked
        target_host = None
        for ip in HIVEMQ_CLUSTER_IPS:
            try:
                s = socket.socket()
                s.settimeout(3)
                s.connect((ip, MQTT_PORT))
                s.close()
                target_host = ip
                break
            except Exception:
                pass
        if not target_host:
            target_host = HIVEMQ_CLUSTER_IPS[0]

    print(f"Connecting to HiveMQ TLS broker ({target_host}:{MQTT_PORT})...")
    client = MQTTClient(
        client_id=MQTT_CLIENT_ID,
        server=target_host,
        port=MQTT_PORT,
        user=MQTT_USER,
        password=MQTT_PASSWORD,
        keepalive=60,
        ssl=True,
        ssl_params={"server_hostname": MQTT_BROKER}
    )
    client.connect()
    print("MQTT Connected successfully over TLS!")
    return client


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

    # Connect WiFi
    if not connect_wifi():
        return

    # Connect MQTT over TLS
    mqtt_client = None
    try:
        mqtt_client = connect_mqtt()
    except Exception as e:
        print(f"[!] MQTT connection failed: {e}")
        print("    Ensure your HiveMQ Cloud user/password is created under 'Access Management'.")
        return

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
    elif part_id == 0x15:
        print("Detected Sensor: MAX30102 (Part ID: 0x15)")
        from max30102 import MAX30102, MAX30105_PULSE_AMP_MEDIUM
        sensor = MAX30102(i2c=i2c)
        sensor.setup_sensor()
        sensor.set_sample_rate(400)
        sensor.set_fifo_average(8)
        sensor.set_active_leds_amplitude(MAX30105_PULSE_AMP_MEDIUM)
        hr_monitor = HeartRateMonitor(window_size=100, smoothing_window=5)
    else:
        print(f"Unknown sensor detected at 0x57 with Part ID: {hex(part_id)}")
        return
    print("Sensor initialized. Streaming telemetry to HiveMQ...\n")

    while True:
        try:
            # Poll sensor data
            if part_id == 0x11:
                samples = sensor.read_sensor()
                if samples:
                    for ir, red in samples:
                        hr_monitor.add_sample(ir)
                        latest_ir = ir
                        latest_red = red
                        if RAW_STREAM:
                            print(f"RAW: IR={ir}, RED={red}")
            elif part_id == 0x15:
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
                    bpm = None
                    hr_monitor.reset()
                else:
                    bpm = hr_monitor.calculate_bpm()
                    if bpm is not None:
                        status = f"Heart Rate: {bpm} BPM"
                    else:
                        status = "Detecting pulse..."

                # Construct payload
                payload = {
                    "bpm": bpm,
                    "ir": latest_ir,
                    "red": latest_red,
                    "status": status,
                    "sensor": "MAX30100" if part_id == 0x11 else "MAX30102",
                    "timestamp": now
                }
                payload_str = ujson.dumps(payload)

                # Publish to HiveMQ Cloud
                try:
                    mqtt_client.publish(MQTT_TOPIC, payload_str.encode())
                    print(f"[MQTT PUB] {payload_str}")
                except Exception as pub_err:
                    print(f"[!] Publish failed ({pub_err}), reconnecting...")
                    try:
                        mqtt_client = connect_mqtt()
                    except Exception as re_err:
                        print(f"[!] Reconnect failed: {re_err}")

                gc.collect()

            time.sleep_ms(20)

        except KeyboardInterrupt:
            print("\nExiting...")
            if mqtt_client:
                mqtt_client.disconnect()
            break
        except Exception as loop_err:
            print(f"[!] Exception in main loop: {loop_err}")
            time.sleep_ms(500)


if __name__ == "__main__":
    main()
