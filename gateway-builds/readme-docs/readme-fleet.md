# RHEM Fleet Specification — Edge AI Train Demo

## Overview

The fleet specification is a YAML document managed by Red Hat Edge Manager (RHEM) that defines the **desired state** of every device in the fleet. When a device enrolls into the fleet, the RHEM agent on that device continuously reconciles its actual state against this specification (automatically deploying containers, applying configuration, and enforcing the OS image version).

---
## Fleet Name

```yaml
metadata:
  name: summit-inference-fleet
```

## Fleet Structure

```
Fleet
├── selector          ← which devices belong to this fleet
├── template
│   └── spec
│       ├── applications  ← containers to run (as Quadlets)
│       ├── config        ← config files to deploy
│       └── os            ← bootc OS image to enforce
```

---

## Selector

```yaml
spec:
  selector:
    matchLabels:
      fleet: inference
```

Any device with the label `fleet: inference` automatically becomes a member of this fleet. Adding the label to a device enrolls it; removing the label removes it from the fleet. This is how you target specific devices for a particular configuration — for example `fleet: inference` for the train demo devices vs `fleet: other-demo` for other booth devices.

The MS-01 device also carries an `alias: ms-01` label for human-readable identification in the RHEM UI.

---

## OS Image

```yaml
os:
  image: quay.io/kenosborn/gateway-summit2k6-bootc:v1
```

This enforces the bootc OS image on every device in the fleet. RHEM will update the device's operating system to this exact image version if it doesn't already match. The OS image is an OCI container image built with RHEL Image Mode (bootc) — it contains the full OS, all system configuration, GDM autologin, SELinux policy, network settings, and the flightctl agent itself.

To roll out an OS update across the fleet, change this image tag and RHEM will stage and apply the update on next check-in.

---

## Applications

```yaml
applications:
  - name: inference
    runAs: demouser
    appType: quadlet
    inline:
      - path: inference.container
        content: |-
          ...
```

### `name: inference`
The application name as it appears in the RHEM UI under the device's Applications panel.

### `runAs: demouser`
Specifies which user the Quadlet runs as on the device. Running as `demouser` gives the container access to the user's session context.

### `appType: quadlet`
Tells RHEM this is a Podman Quadlet — a systemd unit file that manages a container as a system service. RHEM writes the Quadlet file to `/etc/containers/systemd/` and systemd picks it up automatically via the Quadlet generator.

### `inline`
The Quadlet file content is embedded directly in the fleet spec rather than referencing an external file. RHEM deploys this content to the device at the path specified by `path: inference.container`.

---

## The Quadlet

The Quadlet defines how the inference container runs on the device. Each line is explained below:

### [Unit]

```ini
Description=Inference(Edge AI train control)
```
Human-readable name shown in `systemctl status` and the systemd journal.

```ini
After=network-online.target
Wants=network-online.target
```
Ensures the container starts after the network is available — required since it needs to reach the MQTT broker at `10.20.0.150` and pull the image from Quay.

---

### [Container]

```ini
Image=quay.io/kenosborn/inference-train-demo:v2
```
The container image to run. Changing this tag in the fleet spec and saving will cause RHEM to pull the new image and restart the container on next agent check-in.

```ini
AddDevice=/dev/video0
AddDevice=/dev/video1
```
Passes the webcam device nodes into the container so OpenCV can access the camera. Both nodes are passed since the Logitech C922 exposes two V4L2 device entries.

```ini
PublishPort=8080:8080
```
Maps port 8080 on the host to port 8080 in the container, making the Flask MJPEG web stream accessible at `http://<device-ip>:8080`.

```ini
Environment=CAM_W=640
Environment=CAM_H=480
```
Camera capture resolution. 640×480 gives ~30fps on the Logitech C922 in MJPG mode. Higher resolutions (e.g. 1280×720) drop to ~15fps.

```ini
Environment=DISPLAY_SIZE=800
```
The size in pixels of the rendered inference window served via the web stream. Independent of capture resolution — the feed is always scaled to this square size for display.

```ini
Environment=USE_PAPER_GATE=false
```
Disables the brightness pre-filter. When `true`, the model only runs inference if a bright object (e.g. a white placard) is detected in the guide box — a cheap early filter to suppress false positives on empty frames.

```ini
Environment=ARM_THRESHOLD=0.93
```
The model must be at least 93% confident in its top prediction before the system will consider firing a command. Predictions below this threshold are displayed but never acted on.

```ini
Environment=MARGIN_MIN=0.50
```
The gap between the top and second prediction must be at least 50%. Prevents commands from firing when the model is confident but hedging between two classes.

```ini
Environment=STABLE_FRAMES=6
```
The model must return the same class for 6 consecutive frames before a command fires. At 30fps this requires ~0.2 seconds of consistent agreement — prevents transient false positives from triggering commands.

```ini
Environment=COOLDOWN_SEC=3.0
```
Minimum seconds between MQTT commands. Prevents the same command from firing repeatedly while a placard is held in view.

```ini
Environment=MQTT_ENABLED=false
```
Disables MQTT publishing. Set to `true` to enable commands to be sent to the train controller. When `false` the inference window still shows predictions but nothing is sent to the broker.

```ini
Environment=MQTT_BROKER=10.20.0.150
```
IP address of the Mosquitto MQTT broker running on `rhel-util-01`.

```ini
Environment=MQTT_PORT=1883
```
Standard MQTT port. No TLS in this demo setup.

```ini
Environment=MQTT_TOPIC=train/cmd
```
The MQTT topic the inference container publishes to. The Tyrrell train controller subscribes to this same topic.

```ini
SecurityLabelDisable=true
```
Disables SELinux label enforcement for the container. Required because the container accesses `/dev/video*` devices which would otherwise be blocked by the default container SELinux policy.

```ini
User=root
```
Runs the container process as root. Required for camera device access — the V4L2 video devices are owned by the `video` group and root bypasses this restriction.

---

### [Install]

```ini
WantedBy=default.target
```
Ensures the service starts automatically when the system reaches the default (multi-user) target — i.e. on every boot.

---

## How RHEM Enforces Desired State

1. Device enrolls and receives the fleet spec from RHEM
2. flightctl-agent on the device compares current state to desired state
3. If the container isn't running, RHEM starts it
4. If the spec changes (new image, new env var), RHEM restarts the container with the new config
5. If the container is manually killed, RHEM restarts it on the next agent check-in (~60 seconds)

This is the key demo story (desired state enforcement means the device always converges back to what the fleet spec defines, regardless of what happens locally).

---

## Changing Configuration

To change any inference parameter fleet-wide:

1. Edit the relevant `Environment=` line in the fleet spec
2. Save — RHEM detects the spec version has changed
3. Within ~60 seconds the flightctl agent on each device picks up the new spec
4. The container is restarted with the new environment variable

Example — to enable MQTT publishing across the fleet, change:
```
Environment=MQTT_ENABLED=false
```
to:
```
Environment=MQTT_ENABLED=true
```

No SSH, no manual steps, no container rebuild required.

---

## Fleet Metadata

```yaml
metadata:
  name: summit-inference-fleet
  generation: 12
  annotations:
    fleet-controller/templateVersion: v12
```

`generation` increments each time the fleet spec is saved. `templateVersion` tracks which version of the template has been applied to devices — useful for confirming all devices are in sync with the latest spec.

## Device Identity

The MS-01 edge device carries the following identifying information:

| Field | Value |
|-------|-------|
| Fleet | `summit-inference-fleet` |
| Labels | `alias: ms-01`, `fleet: inference` |
| IP | `10.20.0.21` |
| MAC | `58:47:ca:78:f2:58` |
| OS | RHEL 9.7 (Plow) |
| Architecture | amd64 |
| Product | Venus Series (Minisforum MS-01) |
