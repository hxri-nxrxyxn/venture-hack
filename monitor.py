#!/usr/bin/env python3
"""
ESP Live Log & Telemetry Monitor
Supports both USB Serial (UART) monitoring and Cloud MQTT wireless log streaming.
"""
import sys
import time
import glob
import argparse
import datetime

# ANSI Color codes for clean terminal viewing
C_RESET   = "\033[0m"
C_CYAN    = "\033[36m"
C_GREEN   = "\033[32m"
C_YELLOW  = "\033[33m"
C_RED     = "\033[31m"
C_MAGENTA = "\033[35m"
C_BOLD    = "\033[1m"
C_DIM     = "\033[2m"


def auto_detect_port():
    """Auto-detect connected ESP serial port."""
    patterns = [
        "/dev/ttyUSB*",
        "/dev/ttyACM*",
        "/dev/cu.usbserial*",
        "/dev/cu.wchusbserial*",
        "/dev/cu.SLAB_USBtoUART*",
        "COM[0-9]*"
    ]
    matches = []
    for pat in patterns:
        matches.extend(glob.glob(pat))
    return matches[0] if matches else None


def format_log_line(raw_text):
    """Format and colorize serial line."""
    now_str = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    time_tag = f"{C_DIM}[{now_str}]{C_RESET}"

    # Highlight specific event types
    if "[MQTT PUB]" in raw_text:
        return f"{time_tag} {C_GREEN}{C_BOLD}[MQTT PUB]{C_RESET} {raw_text.replace('[MQTT PUB]', '').strip()}"
    elif "Connected" in raw_text or "SUCCESS" in raw_text or "Online" in raw_text:
        return f"{time_tag} {C_GREEN}{raw_text}{C_RESET}"
    elif "[!]" in raw_text or "Error" in raw_text or "FAILED" in raw_text or "Exception" in raw_text or "Traceback" in raw_text:
        return f"{time_tag} {C_RED}{raw_text}{C_RESET}"
    elif "Connecting" in raw_text or "..." in raw_text:
        return f"{time_tag} {C_YELLOW}{raw_text}{C_RESET}"
    elif "Platform:" in raw_text or "Sensor:" in raw_text or "Detected" in raw_text:
        return f"{time_tag} {C_CYAN}{raw_text}{C_RESET}"
    return f"{time_tag} {raw_text}"


def run_serial_monitor(port, baudrate=115200, reset_on_start=False):
    """Monitor live logs from ESP via USB serial."""
    import serial

    if not port:
        port = auto_detect_port()

    if not port:
        print(f"{C_RED}[!] No ESP serial port detected.{C_RESET}")
        print("    Plug in your ESP board or specify manually with: python3 monitor.py -p /dev/ttyUSB0")
        sys.exit(1)

    print(f"{C_CYAN}{C_BOLD}=== ESP Serial Monitor ==={C_RESET}")
    print(f" Port:     {C_BOLD}{port}{C_RESET}")
    print(f" Baudrate: {C_BOLD}{baudrate}{C_RESET}")
    print(f" Controls: {C_DIM}Press Ctrl+C to exit{C_RESET}\n")

    while True:
        try:
            with serial.Serial(port, baudrate, timeout=0.1) as ser:
                if reset_on_start:
                    print(f"{C_YELLOW}[*] Triggering hardware reset (RTS pulse)...{C_RESET}")
                    ser.dtr = False
                    ser.rts = True
                    time.sleep(0.1)
                    ser.rts = False
                    time.sleep(0.2)
                    reset_on_start = False  # Only reset on initial connect

                print(f"{C_GREEN}[*] Serial connected. Streaming logs...{C_RESET}\n")

                line_buf = bytearray()
                while True:
                    data = ser.read(128)
                    if data:
                        line_buf.extend(data)
                        while b"\n" in line_buf:
                            raw_line, line_buf = line_buf.split(b"\n", 1)
                            text = raw_line.decode("utf-8", "replace").rstrip("\r")
                            if text:
                                print(format_log_line(text))
                    else:
                        time.sleep(0.01)

        except serial.SerialException as e:
            print(f"\n{C_YELLOW}[!] Serial disconnected ({e}). Reconnecting in 2s...{C_RESET}")
            time.sleep(2)
        except KeyboardInterrupt:
            print(f"\n{C_CYAN}[*] Serial monitor closed.{C_RESET}")
            break


def run_mqtt_monitor(broker, port, user, password, topic):
    """Monitor live logs / telemetry wirelessly via HiveMQ Cloud."""
    import ssl
    import json
    try:
        from lib.umqtt.simple import MQTTClient
    except ImportError:
        import urllib.request
        print(f"{C_RED}[!] umqtt module not found locally.{C_RESET}")
        return

    print(f"{C_CYAN}{C_BOLD}=== ESP Wireless MQTT Monitor ==={C_RESET}")
    print(f" Broker: {C_BOLD}{broker}:{port}{C_RESET}")
    print(f" Topic:  {C_BOLD}{topic.decode() if isinstance(topic, bytes) else topic}{C_RESET}")
    print(f" Controls: {C_DIM}Press Ctrl+C to exit{C_RESET}\n")

    ctx = ssl.create_default_context()
    client_id = f"log_monitor_{int(time.time())}"
    client = MQTTClient(
        client_id=client_id,
        server=broker,
        port=port,
        user=user,
        password=password,
        ssl=ctx
    )

    def on_message(recv_topic, payload):
        now_str = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        time_tag = f"{C_DIM}[{now_str}]{C_RESET}"
        raw = payload.decode("utf-8", "replace")
        try:
            d = json.loads(raw)
            # Pretty-print telemetry summary
            summary = []
            if "ndvi" in d: summary.append(f"NDVI: {C_BOLD}{d['ndvi']:+.3f}{C_RESET}")
            if "status" in d: summary.append(f"Status: {C_GREEN}{d['status']}{C_RESET}")
            if "spad" in d: summary.append(f"SPAD: {d['spad']}")
            if "bpm" in d: summary.append(f"BPM: {C_BOLD}{d['bpm']}{C_RESET}")
            if "ir" in d: summary.append(f"IR: {d['ir']}")
            if "red" in d: summary.append(f"RED: {d['red']}")
            print(f"{time_tag} {C_GREEN}[MQTT RX]{C_RESET} " + " | ".join(summary))
        except Exception:
            print(f"{time_tag} {C_GREEN}[MQTT RX]{C_RESET} {raw}")

    client.set_callback(on_message)
    print(f"{C_YELLOW}[*] Connecting to HiveMQ Cloud TLS...{C_RESET}")
    client.connect()
    topic_bytes = topic if isinstance(topic, bytes) else topic.encode()
    client.subscribe(topic_bytes)
    print(f"{C_GREEN}[*] Subscribed to {topic_bytes.decode()}. Waiting for telemetry packets...{C_RESET}\n")

    try:
        while True:
            try:
                client.check_msg()
            except (OSError, ssl.SSLWantReadError):
                pass
            time.sleep(0.05)
    except KeyboardInterrupt:
        print(f"\n{C_CYAN}[*] MQTT monitor closed.{C_RESET}")
        try:
            client.disconnect()
        except:
            pass


def main():
    parser = argparse.ArgumentParser(description="Live log viewer for ESP8266 / ESP32 (Serial & MQTT)")
    parser.add_argument("-p", "--port", default=None, help="Serial port (auto-detected if omitted)")
    parser.add_argument("-b", "--baud", type=int, default=115200, help="Baudrate (default: 115200)")
    parser.add_argument("-r", "--reset", action="store_true", help="Trigger a soft-reset on start to see boot logs")
    parser.add_argument("--mqtt", action="store_true", help="Monitor telemetry wirelessly over HiveMQ Cloud MQTT instead of serial")
    parser.add_argument("--topic", default="esptool/sensor/data", help="MQTT topic to monitor (default: esptool/sensor/data)")

    args = parser.parse_args()

    if args.mqtt:
        run_mqtt_monitor(
            broker="99db9c66011f4f0d955e8e8b8fade3cd.s1.eu.hivemq.cloud",
            port=8883,
            user="hakku04",
            password="Hari@2004",
            topic=args.topic
        )
    else:
        run_serial_monitor(args.port, args.baud, args.reset)


if __name__ == "__main__":
    main()
