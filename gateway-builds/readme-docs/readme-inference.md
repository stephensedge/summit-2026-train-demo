# Edge Gateway Inference (How It Works)

## Overview

The inference system uses a webcam to continuously classify hand-held placards and send commands to an industrial train controller via MQTT. It runs entirely on an edge device with no cloud or internet dependency (all inference happens on-device using a pre-trained ONNX model).

The system has two variants:

- **`inference_cv.py`** : displays output via an OpenCV window (requires X11 display) (I couldn't get this to open on the gnome desktop when deployed via RHEM so I switched to the view via browser mechanism on port 8080 below)
- **`inference_web.py`** : streams output via a Flask MJPEG web server on port 8080 (no display dependency)

------

## Model

The model is **MobileNetV3 Small**, a compact neural network designed for efficient inference on edge hardware. It was trained using transfer learning (starting from a model pre-trained on ImageNet and fine-tuning only the classifier head on placard images).

The model is exported to **ONNX format** after training, which removes the PyTorch dependency entirely. At runtime, **ONNX Runtime** loads and executes the model. The inference container has no PyTorch installed.

**Classes:** `none`, `start`, `stop`, `slow`, `reverse`

**Input:** 224×224 RGB image

**Output:** 5 confidence scores (softmax probabilities summing to 1.0)

------

## Inference Pipeline

Each camera frame goes through the following steps:

### 1. Capture

A frame is read from the webcam via OpenCV. The camera is initialized in MJPG mode via V4L2 to achieve 30fps at 640×480 resolution.

### 2. Center Square Crop

The frame is cropped to a square using the shorter dimension. This defines the **guide box** — the region the model evaluates. Everything outside the guide box is ignored.

### 3. Paper Gate *(optional, `USE_PAPER_GATE=true`)*

Before running the model, a brightness check filters out frames with no placard present. The guide box is converted to grayscale and pixels above `BRIGHT_THRESH` are counted. If the fraction of bright pixels is below `MIN_BRIGHT_FRAC` or the center fraction is below `MIN_CENTER_BRIGHT`, inference is skipped and the frame is classified as `none`. This is a cheap pre-filter that prevents unnecessary inference on empty frames.

### 4. Preprocessing

The cropped square is resized to 224×224, converted to RGB, normalized to [0.0, 1.0], and transposed to CHW format (channels first) as required by the model.

### 5. Inference

The preprocessed image is passed through the ONNX model using ONNX Runtime's CPU execution provider. The model outputs raw logits which are converted to probabilities via softmax.

### 6. ARM_THRESHOLD Gate

The top prediction's confidence must exceed `ARM_THRESHOLD` (default 0.93 = 93%) for the system to arm. Below this threshold the prediction is displayed but no command will ever fire.

### 7. MARGIN_MIN Gate

Even if the top prediction clears `ARM_THRESHOLD`, the gap between the top and second prediction must exceed `MARGIN_MIN` (default 0.50 = 50%). This catches cases where the model is confident but hedging between two classes. For example, if `stop=94%` and `start=48%`, the margin is only 0.46 and the system stays disarmed.

### 8. STABLE_FRAMES Gate

Once both threshold and margin gates pass, a streak counter increments. The model must return the same class for `STABLE_FRAMES` consecutive frames (default 6) before a command fires. At 30fps this requires approximately 0.2 seconds of consistent agreement. Any frame that fails either gate resets the streak counter to zero.

### 9. MQTT Publish

When all three gates pass, a JSON command is published to the MQTT broker:

```json
{
  "cmd": "stop",
  "confidence": 0.9857,
  "device": "ms01-camera",
  "model": "placards-v1"
}
```

A cooldown timer (`COOLDOWN_SEC`, default 1.0 second) prevents the same command from firing repeatedly.

------

## Display

### inference_web.py (web streaming variant)

The inference loop runs in a background thread. Each frame, the annotated canvas is JPEG-encoded and placed in a shared memory buffer. A Flask web server running in the main thread serves this buffer as an MJPEG stream at `http://localhost:8080`. Any browser on the local network can connect to view the live feed.

### Canvas Layout

The display is a portrait layout  (black background, camera feed on top, status panel below):

```
┌─────────────────────┐
│                     │
│    Camera Feed      │  ← DISPLAY_SIZE × DISPLAY_SIZE px
│    + Guide Box      │
│                     │
├─────────────────────┤
│   PREDICTION:       │
│   STOP              │  ← 300px status panel
│   Confidence: 95%   │
│   [debug metrics]   │
└─────────────────────┘
```

**Guide box colors:**

- White — idle, below threshold
- Cyan — armed, above threshold, building streak
- Green — command just fired

------

## Environment Variables

All parameters are configurable at runtime via environment variables — no rebuild required.

| Variable               | Default       | Description                                    |
| ---------------------- | ------------- | ---------------------------------------------- |
| `CAMERA_INDEX`         | `0`           | V4L2 camera device index                       |
| `CAM_W`                | `640`         | Camera capture width                           |
| `CAM_H`                | `480`         | Camera capture height                          |
| `EXPOSURE`             | `-1`          | Camera exposure (-1=auto, positive=manual)     |
| `DISPLAY_SIZE`         | `800`         | Display window size in pixels                  |
| `WEB_PORT`             | `8080`        | Flask web server port                          |
| `ARM_THRESHOLD`        | `0.85`        | Minimum confidence to arm (0.0-1.0)            |
| `STABLE_FRAMES`        | `3`           | Consecutive frames required to trigger         |
| `COOLDOWN_SEC`         | `1.0`         | Seconds between commands                       |
| `MARGIN_MIN`           | `0.20`        | Minimum gap between top two predictions        |
| `USE_PAPER_GATE`       | `true`        | Enable brightness pre-filter                   |
| `BRIGHT_THRESH`        | `185`         | Per-pixel brightness threshold (0-255)         |
| `MIN_BRIGHT_FRAC`      | `0.18`        | Minimum fraction of bright pixels in guide box |
| `MIN_CENTER_BRIGHT`    | `0.12`        | Minimum fraction of bright pixels in center    |
| `MQTT_ENABLED`         | `false`       | Enable MQTT publishing                         |
| `MQTT_BROKER`          | `localhost`   | MQTT broker hostname or IP                     |
| `MQTT_PORT`            | `1883`        | MQTT broker port                               |
| `MQTT_TOPIC`           | `train/cmd`   | MQTT topic to publish commands                 |
| `DEVICE_ID`            | `ms01-camera` | Device identifier in MQTT payload              |
| `MODEL_VERSION`        | `placards-v1` | Model version identifier in MQTT payload       |
| `SHOW_DEBUG_ON_SCREEN` | `true`        | Show debug metrics on display                  |

------

## Stack Summary

| Component          | Technology                       |
| ------------------ | -------------------------------- |
| Edge OS            | RHEL 9 Image Mode (bootc)        |
| Container runtime  | Podman                           |
| Service management | Systemd Quadlet                  |
| Fleet management   | Red Hat Edge Manager (RHEM)      |
| Model architecture | MobileNetV3 Small                |
| Model format       | ONNX                             |
| Inference engine   | ONNX Runtime                     |
| Camera capture     | OpenCV + V4L2                    |
| Web streaming      | Flask MJPEG                      |
| Messaging          | MQTT (paho-mqtt)                 |
| Training framework | PyTorch (not present at runtime) |