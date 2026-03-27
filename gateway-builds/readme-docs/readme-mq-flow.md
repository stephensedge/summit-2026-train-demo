# MQTT Message Flow — Edge AI Train Demo

## Overview

When the inference container recognizes a placard, it publishes a command to an MQTT broker. The Tyrrell train controller subscribes to that broker and acts on the command.

## Message Format

When all three inference gates pass (ARM_THRESHOLD, MARGIN_MIN, STABLE_FRAMES), the inference container publishes a JSON message to the broker:

```json
{
  "cmd": "stop",
  "confidence": 0.9857,
  "device": "ms01-camera",
  "model": "placards-v1"
}
```

## The Broker

Mosquitto is running on `rhel-util-01` at `10.20.0.150` on port 1883. It receives messages from the inference container and delivers them to any subscribers on the `train/cmd` topic.

## End-to-End Flow

```
MS-01 camera
  → inference container
    → paho-mqtt publish to 10.20.0.150:1883
      → Mosquitto broker (rhel-util-01)
        → Tyrrell controller subscribes
          → train moves
```

## Key Configuration

These environment variables in the Quadlet control MQTT behavior:

| Variable        | Value         | Description                             |
| --------------- | ------------- | --------------------------------------- |
| `MQTT_ENABLED`  | `true`        | Enables publishing                      |
| `MQTT_BROKER`   | `10.20.0.150` | Mosquitto broker IP (rhel-util-01)      |
| `MQTT_PORT`     | `1883`        | Mosquitto broker port                   |
| `MQTT_TOPIC`    | `train/cmd`   | Topic to publish commands on            |
| `COOLDOWN_SEC`  | `1.0`         | Minimum seconds between commands        |
| `DEVICE_ID`     | `ms01-camera` | Device identifier in the payload        |
| `MODEL_VERSION` | `placards-v1` | Model version identifier in the payload |

## Code Walkthrough

The MQTT publishing code lives in `inference_web.py` inside the trigger block — it only fires after all three inference gates pass (ARM_THRESHOLD, MARGIN_MIN, STABLE_FRAMES):

```python
if MQTT_ENABLED:
    try:
        import paho.mqtt.publish as mqtt_publish
        payload = json.dumps({
            "cmd":        trigger_label,
            "confidence": round(float(conf1), 4),
            "device":     DEVICE_ID,
            "model":      MODEL_VERSION,
        })
        mqtt_publish.single(
            MQTT_TOPIC,
            payload=payload,
            hostname=MQTT_BROKER,
            port=MQTT_PORT,
        )
        print(f"  MQTT → {MQTT_BROKER}:{MQTT_PORT} {MQTT_TOPIC} {payload}", flush=True)
    except Exception as mqtt_err:
        print(f"  MQTT ERROR: {mqtt_err}", flush=True)
```

**Key design decisions:**

- **`if MQTT_ENABLED`** — the entire MQTT block is skipped if `MQTT_ENABLED=false`, so the container can run in display-only mode with no broker required
- **Lazy import** — `paho.mqtt.publish` is imported inside the trigger block rather than at the top of the file, so a missing broker at startup doesn't crash the container
- **`mqtt_publish.single()`** — opens a connection, publishes one message, and closes immediately. Stateless — no persistent connection is maintained between triggers
- **`try/except`** — if the broker is unreachable the error is logged but inference continues uninterrupted. The demo won't crash just because MQTT fails
- **`flush=True`** — forces the print to appear immediately in the systemd journal rather than being buffered

## Monitoring

To watch MQTT messages in real time on rhel-util-01:

```bash
podman exec -it mosquitto mosquitto_sub -h localhost -p 1883 -t "train/cmd" -v
```

To watch the inference container logs including TRIGGER events on the MS-01:

```bash
journalctl -u inference-371382-inference.service -f
```