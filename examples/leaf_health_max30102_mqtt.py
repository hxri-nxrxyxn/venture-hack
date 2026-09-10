"""
Leaf Optical Health & Chlorophyll (NDVI) Analyzer - MAX30102 Edition
High-stability, auto-recovering streamer for ESP8266 / ESP32.
"""
import sys
import time
import math
import gc
import ujson
import network
from machine import Pin, SoftI2C
from max30102 import MAX30102
from umqtt.simple import MQTTClient

# ── Configuration ────────────────────────────────────────────────────────────
WIFI_SSID = "Nothing 4a Pro"
WIFI_PASSWORD = "hlothisisme:)"

MQTT_BROKER = "99db9c66011f4f0d955e8e8b8fade3cd.s1.eu.hivemq.cloud"
MQTT_PORT = 8883
MQTT_CLIENT_ID = "esp_leaf_analyzer"
MQTT_USER = "hakku04"
MQTT_PASSWORD = "Hari@2004"
MQTT_TOPIC = b"esptool/sensor/data"
HIVEMQ_CLUSTER_IPS = ["52.31.149.80", "46.137.47.218", "54.73.92.158"]

DEFAULT_WHITE_RED = 150000.0
DEFAULT_WHITE_IR  = 150000.0
REPORT_INTERVAL_MS = 1500


def get_i2c_pins():
    if sys.platform == "esp8266":
        return 4, 5
    elif sys.platform == "esp32":
        return 21, 22
    elif sys.platform == "rp2":
        return 16, 17
    return 4, 5


def classify_leaf_health(ndvi, rvi):
    if ndvi >= 0.45:
        return "Healthy (High Chlorophyll)"
    elif ndvi >= 0.25:
        return "Moderate (Mild Stress / Maturing)"
    elif ndvi >= 0.08:
        return "Chlorotic (Yellowing / Deficiency)"
    else:
        return "Necrotic / Senescent (Dead Tissue)"


def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if wlan.isconnected():
        print(f"WiFi already connected! IP: {wlan.ifconfig()[0]}")
        return True
    print(f"Connecting to WiFi '{WIFI_SSID}'...")
    try:
        wlan.disconnect()
    except:
        pass
    time.sleep_ms(500)
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


def connect_mqtt():
    last_err = None
    for target_host in HIVEMQ_CLUSTER_IPS:
        client = None
        try:
            print(f"Connecting to HiveMQ TLS ({target_host}:{MQTT_PORT})...")
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
            client.connect(timeout=8)
            print("MQTT Connected successfully over TLS!")
            return client
        except Exception as e:
            last_err = e
            print(f"[!] Node {target_host} error ({e}), trying next node...")
            if client and client.sock:
                try:
                    client.sock.close()
                except:
                    pass
    raise last_err


def main():
    sda_num, scl_num = get_i2c_pins()
    print(f"Platform: {sys.platform} | SDA=Pin({sda_num}), SCL=Pin({scl_num})")

    # Connect WiFi
    while not connect_wifi():
        print("Retrying WiFi in 3 seconds...")
        time.sleep(3)

    # Connect MQTT
    mqtt_client = None
    try:
        mqtt_client = connect_mqtt()
    except Exception as e:
        print(f"[!] Initial MQTT connection failed ({e}), will retry in loop.")

    # Initialize I2C
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
    print(f"Detected Sensor: MAX30102 (Part ID: {hex(part_id)}, Rev ID: {hex(rev_id)})")

    # Configure MAX30102 with stable sampling
    sensor = MAX30102(i2c=i2c)
    sensor.setup_sensor()
    # 100 Hz sampling with 8x FIFO averaging = 12.5 effective samples/sec
    # (Optimal for ESP8266 RAM/I2C and leaf tissue reflectance)
    sensor.set_sample_rate(100)
    sensor.set_fifo_average(8)
    sensor.set_active_leds_amplitude(0xFF)  # Full optical drive

    try:
        temp = round(sensor.read_temperature(), 1)
    except:
        temp = None

    print("MAX30102 Leaf Health Streamer Active. Continuous streaming started.\n")

    ir_acc = 0
    red_acc = 0
    count = 0
    ref_time = time.ticks_ms()

    while True:
        try:
            # Poll sensor data
            sensor.check()
            while sensor.available():
                red = sensor.pop_red_from_storage()
                ir = sensor.pop_ir_from_storage()
                ir_acc += ir
                red_acc += red
                count += 1
        except Exception:
            time.sleep_ms(10)

        now = time.ticks_ms()
        if time.ticks_diff(now, ref_time) >= REPORT_INTERVAL_MS:
            ref_time = now

            if count == 0:
                # Recover sensor FIFO if pointers ever desynchronize
                try:
                    sensor.clear_fifo()
                except:
                    pass
                continue

            avg_ir = ir_acc / count
            avg_red = red_acc / count
            ir_acc = 0
            red_acc = 0
            count = 0

            # Check optical condition
            if avg_ir > 255000 or avg_red > 255000:
                status = "Optical Saturation"
                ndvi = 0.0
                rvi = 0.0
                spad_est = 0.0
            elif avg_ir < 1000 and avg_red < 1000:
                status = "Waiting for leaf sample..."
                ndvi = 0.0
                rvi = 0.0
                spad_est = 0.0
            else:
                norm_ir = avg_ir / DEFAULT_WHITE_IR
                norm_red = avg_red / DEFAULT_WHITE_RED
                denom = norm_ir + norm_red
                if denom > 0:
                    ndvi = (norm_ir - norm_red) / denom
                else:
                    ndvi = 0.0
                ndvi = max(-1.0, min(1.0, ndvi))
                rvi = (norm_ir / norm_red) if norm_red > 0.001 else 99.9
                try:
                    spad_est = round(10.0 * math.log(rvi), 1) if rvi > 0 else 0.0
                except:
                    spad_est = 0.0
                status = classify_leaf_health(ndvi, rvi)

            payload = {
                "type": "leaf_health",
                "sensor": "MAX30102",
                "ndvi": round(ndvi, 3),
                "rvi": round(rvi, 2),
                "spad": spad_est,
                "status": status,
                "ir": int(avg_ir),
                "red": int(avg_red),
                "temp": temp,
                "timestamp": now
            }
            payload_str = ujson.dumps(payload)

            # Safe, non-blocking MQTT send and reconnect
            if mqtt_client is not None:
                try:
                    if hasattr(mqtt_client, "sock") and mqtt_client.sock:
                        try:
                            mqtt_client.sock.settimeout(5)
                        except:
                            pass
                    mqtt_client.publish(MQTT_TOPIC, payload_str.encode())
                    print(f"[MQTT PUB] {payload_str}")
                except Exception as pub_err:
                    print(f"[!] Publish failed ({pub_err}), resetting connection...")
                    try:
                        mqtt_client.disconnect()
                    except:
                        pass
                    mqtt_client = None
            else:
                wlan = network.WLAN(network.STA_IF)
                if not wlan.isconnected():
                    print("[!] WiFi connection lost, reconnecting...")
                    connect_wifi()
                try:
                    mqtt_client = connect_mqtt()
                except Exception as re_err:
                    print(f"[!] Reconnect failed: {re_err}")

            gc.collect()

        time.sleep_ms(15)


if __name__ == "__main__":
    main()
