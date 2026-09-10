# venture-hack: MicroPython MAX30100 & MAX30102 Driver Suite

A lightweight, robust MicroPython library and application suite for **MAX30100** and **MAX30102** pulse oximeter and heart-rate sensors, optimized for **ESP8266** and **ESP32** microcontrollers.

---

## Features

- **Dual Sensor Support**: Automatically detects and drives both **MAX30100** (Part ID `0x11`) and **MAX30102** (Part ID `0x15`).
- **ESP8266 RAM Optimized**: Modular architecture compatible with precompiled `.mpy` bytecode to prevent heap `MemoryError` on low-RAM devices.
- **Fault-Tolerant I2C**: Gracefully handles bus jitter and transient NACKs on jumper wires.
- **Heart Rate Monitor**: Real-time moving-average filter and dynamic threshold peak detector for BPM calculation.
- **Raw PPG Serial Streaming**: CSV-formatted output ready for Arduino IDE Serial Plotter or custom graphing tools.
- **Internal Die Temperature**: Read sensor temperature for calibration.

---

## Hardware Wiring

### ESP8266 (NodeMCU / Wemos D1 Mini)

| Sensor Pin | ESP8266 Pin | GPIO Number | Notes |
| :--- | :--- | :--- | :--- |
| **VIN** / **VCC** | **3V3** or **VU (5V)** | — | Use **VU (5V)** if your breakout board has an onboard LDO regulator that drops 3.3V too low |
| **GND** | **GND** | — | Ground reference |
| **SDA** | **D2** | GPIO 4 | I2C Data (Internal pull-up enabled) |
| **SCL** | **D1** | GPIO 5 | I2C Clock (Internal pull-up enabled) |

### ESP32

| Sensor Pin | ESP32 Pin | GPIO Number |
| :--- | :--- | :--- |
| **VIN** / **VCC** | **3V3** or **5V** | — |
| **GND** | **GND** | — |
| **SDA** | **GPIO 21** | GPIO 21 |
| **SCL** | **GPIO 22** | GPIO 22 |

---

## The MAX30100 vs. MAX30102 Clone Issue

Many breakout boards sold on Amazon, AliExpress, and eBay labeled as **"MAX30102"** actually have a **MAX30100** chip mounted on them.
- Standard MAX30102 registers differ from MAX30100 (FIFO addresses, LED current registers, and Part ID).
- An authentic MAX30102 returns Part ID `0x15`.
- A MAX30100 returns Part ID `0x11`.

The examples in this repository query register `0xFF` at startup and automatically route to the correct driver routines.

---

## Project Structure

```text
venture-hack/
├── .gitignore
├── README.md
├── requirements.txt
├── main.py                     # Main microcontroller entrypoint
├── lib/
│   ├── max30100.py             # MAX30100 MicroPython driver
│   └── max30102/               # MAX30102 MicroPython driver
│       ├── __init__.py
│       └── circular_buffer.py
└── examples/
    ├── basic_reading.py        # Streams raw RED & IR optical readings
    └── heart_rate_bpm.py       # Live BPM estimation & pulse detection
```

---

## Getting Started

### 1. Install Host Dependencies
On your computer:
```bash
pip install -r requirements.txt
```

### 2. Deploy Drivers to Microcontroller
Upload the drivers to the `/lib` directory on the board using `ampy`:

```bash
# Set your serial port (e.g., /dev/ttyUSB0 on Linux, COM3 on Windows)
export AMPY_PORT=/dev/ttyUSB0
export AMPY_DELAY=1

# Create /lib on the board
ampy mkdir --exists-okay /lib

# For ESP8266: compile to .mpy first for optimal memory usage
mpy-cross lib/max30100.py
mpy-cross lib/max30102/__init__.py
mpy-cross lib/max30102/circular_buffer.py

# Upload compiled drivers
ampy put lib/max30100.mpy /lib/max30100.mpy
ampy mkdir --exists-okay /lib/max30102
ampy put lib/max30102/__init__.mpy /lib/max30102/__init__.mpy
ampy put lib/max30102/circular_buffer.mpy /lib/max30102/circular_buffer.mpy
```

---

## Running the Examples

### 1. Basic PPG Optical Reading (RED & IR)
Streams raw values formatted for Arduino Serial Plotter:
```bash
ampy run examples/basic_reading.py
```
*Output sample:*
```text
Platform: esp8266 | SDA=Pin(4), SCL=Pin(5)
I2C Scan: ['0x57']
Detected Sensor: MAX30100 (Part ID: 0x11)
Die Temperature: 28.5 °C

Streaming IR & RED readings:
IR, RED
21886, 27526
21932, 27547
21849, 27509
```

### 2. Heart Rate BPM Estimation
Estimates beats per minute (place finger gently on the sensor):
```bash
ampy run examples/heart_rate_bpm.py
```
*Output sample:*
```text
Platform: esp8266 | SDA=Pin(4), SCL=Pin(5)
Detected Sensor: MAX30100 (Part ID: 0x11)
Place your finger gently over the sensor. Calculating BPM every 2 seconds...
Heart Rate: 72 BPM
Heart Rate: 74 BPM
```

---

## License
MIT License
