#!/usr/bin/env python3

import os
import sys
import paho.mqtt.client as mqtt
from pymodbus.client import ModbusSerialClient
from pymodbus.pdu import ExceptionResponse
from prometheus_client import CollectorRegistry, Gauge, push_to_gateway

# --- Configuration ---
# MQTT configuration via environment variables
MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "motor/control")

# Prometheus config
PUSHGATEWAY_URL = os.getenv("PUSHGATEWAY_URL", "http://localhost:9091")

# Voltage Control Parameters
MAX_VOLTAGE = 10.3
MIN_VOLTAGE = 0.0
START_VOLTAGE = 5.0
STEP_VOLTAGE = 1.0

# --- Global State ---
current_voltage = 0.0

# --- Prometheus Setup ---
registry = CollectorRegistry()
metrics = {
    'voltage': Gauge('voltage', 'Voltage from analog output 0', ['output'], registry=registry),
    'register': Gauge('register', 'Modbus register for analog output 0', ['output'], registry=registry),
    'raw_value': Gauge('raw_value', 'Converted raw value for modbus on analog output 0', ['output'], registry=registry),
}

# --- Modbus Setup ---
modbus_client = ModbusSerialClient(
    port="/dev/mtx_tty_mb",
    baudrate=115200,
    parity="N",
    stopbits=1,
    bytesize=8,
    timeout=1
)

def set_motor_voltage(volts):
    global current_voltage
    
    # Ensure voltage is strictly bounded between limits
    volts = max(MIN_VOLTAGE, min(MAX_VOLTAGE, volts))
    current_voltage = volts

    # Convert to 16-bit Modbus value
    val = int((volts / 10.3) * 65535)
    register = 0x6000
    unit_id = 188

    # Update Prometheus metrics locally
    metrics['voltage'].labels(output='ao0').set(volts)
    metrics['register'].labels(output='ao0').set(register)
    metrics['raw_value'].labels(output='ao0').set(val)

    # Reconnect to Modbus if disconnected
    if not modbus_client.is_socket_open():
        modbus_client.connect()

    # Write to Modbus (Using device_id for PyModbus 3.12+)
    response = modbus_client.write_registers(register, [val], device_id=unit_id)

    # Check Modbus response
    if isinstance(response, ExceptionResponse):
        print(f"Modbus error: {response}")
    elif response.isError():
        print(f"Modbus communication error")
    else:
        print(f"AO set successfully to {volts:.2f}V (Raw: {val})")

    # Push to Prometheus (Fail gracefully if unreachable)
    try:
        push_to_gateway(PUSHGATEWAY_URL, job='AO0_output', registry=registry)
    except Exception as e:
        print(f"Warning: Could not push metrics to {PUSHGATEWAY_URL}. Error: {e}")

# --- MQTT Callbacks ---
def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print(f"Connected to MQTT broker at {MQTT_BROKER}:{MQTT_PORT}")
        client.subscribe(MQTT_TOPIC)
        print(f"Subscribed to topic: {MQTT_TOPIC}")
    else:
        print(f"Failed to connect to MQTT, return code {rc}")

def on_message(client, userdata, msg):
    global current_voltage
    command = msg.payload.decode('utf-8').strip().lower()
    print(f"Received command: '{command}'")

    new_voltage = current_voltage

    if command == "stop":
        new_voltage = MIN_VOLTAGE
    elif command == "start":
        # If already stopped, jump to the defined START voltage
        if current_voltage == MIN_VOLTAGE:
            new_voltage = START_VOLTAGE
    elif command == "fast":
        new_voltage += STEP_VOLTAGE
    elif command == "slow":
        new_voltage -= STEP_VOLTAGE
    else:
        print(f"Ignored unknown command: {command}")
        return

    # Apply only if the voltage has actually changed
    if new_voltage != current_voltage:
        set_motor_voltage(new_voltage)
    else:
        print(f"Voltage already at limits or running. Current: {current_voltage:.2f}V")

# --- Main Loop ---
def main():
    print("Starting Motor Control Service...")

    # Initialize to 0V on startup for safety
    set_motor_voltage(MIN_VOLTAGE)

    # Explicitly use VERSION1 to suppress the paho-mqtt deprecation warning
    try:
        mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
    except AttributeError:
        # Fallback for older paho-mqtt versions
        mqtt_client = mqtt.Client()

    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message

    try:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
    except Exception as e:
        print(f"Cannot connect to MQTT broker: {e}")
        sys.exit(1)

    try:
        # Start the blocking MQTT loop
        mqtt_client.loop_forever()
    except KeyboardInterrupt:
        print("\nShutting down gracefully...")
    finally:
        # Safety shutdown: Ensure motor stops before exiting
        set_motor_voltage(MIN_VOLTAGE)
        modbus_client.close()
        mqtt_client.disconnect()

if __name__ == "__main__":
    main()