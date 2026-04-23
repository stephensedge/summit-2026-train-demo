# Inference Container — Dashboard Variant

A fork of `gateway-builds/inference-container/` that adds a Red Hat branded
trade-show dashboard around the existing placard inference engine. The
inference loop (camera → ONNX → paper-gate → trigger → MQTT) is **unchanged** —
everything here is pure observability and presentation.

See `../inference-container/` for the original.


## What it serves

| Path | Purpose |
| --- | --- |
| `/`            | Full dashboard (logo, clock, prediction card, recent commands, MQTT, OCP cluster bar, live log strip). Designed for a wall-mounted TV. |
| `/feed`        | Minimal camera-only page — fills the browser window. Use for tiling (snap-left + other stuff on the right). |
| `/logs`        | Standalone terminal-style live log page — captures the same output as `podman logs -f`. Useful as a tileable companion to `/feed`. |
| `/stream`      | Raw MJPEG video stream (the underlying feed that `/` and `/feed` embed). Same URL the original container served. |
| `/api/status`  | JSON: current prediction, FPS, recent triggers, MQTT target, OCP node metrics. |
| `/api/logs`    | JSON: rolling in-memory stdout capture, pollable with `?since=<seq>`. |


## Quick start

```sh
cd gateway-builds/inference-container-dashboard
podman build -t inference-dashboard:dev .

podman run -d --name inference-dashboard \
  --device /dev/video0 \
  --security-opt label=disable \
  -p 8080:8080 \
  -e DEVICE_ID=gateway-01 \
  inference-dashboard:dev
```

Open `http://localhost:8080/`.


## Environment variables

### Dashboard branding

These control the header on `/` only. All are optional.

| Var | Default | Effect |
| --- | --- | --- |
| `SITE_TITLE_LEAD` | `Red Hat`                                   | First part of the header title (black text) |
| `SITE_TITLE`      | `Edge AI Train Demo`                        | Second part of the header title (red accent) |
| `SITE_SUBTITLE`   | `Summit 2026 · OpenShift + Edge Manager`    | Subtitle under the title |
| `DEVICE_ID`       | `ms01-camera`                               | Identifier shown on `/feed` caption, `/logs` header, `/api/status` |
| `MODEL_VERSION`   | `placards-v1`                               | Shown in the MQTT card |

Example — one demo repurposed for a different event:

```sh
podman run ... \
  -e SITE_TITLE_LEAD="Acme Corp" \
  -e SITE_TITLE="Quality Line Vision" \
  -e SITE_SUBTITLE="Plant 4 · Cell B" \
  -e DEVICE_ID="cell-b-cam-3" \
  inference-dashboard:dev
```

### Dashboard internals

| Var | Default | Effect |
| --- | --- | --- |
| `RECENT_LIMIT`   | `10`  | Max entries in the Recent Commands card (`/api/status.recent`) |
| `LOG_RING_SIZE`  | `500` | Max lines kept in the in-memory stdout ring buffer (`/logs`, `/api/logs`) |

### OCP cluster metrics (optional)

The cluster-bar at the bottom of `/` pulls node CPU / memory / temperature from
a Prometheus-compatible endpoint. If `OCP_PROMETHEUS_URL` isn't set (or the
endpoint is unreachable), the cluster-bar shows node names with `—` for all
values and a subtitle of `telemetry offline`. The inference pipeline itself
never blocks on these queries.

| Var | Default | Effect |
| --- | --- | --- |
| `OCP_PROMETHEUS_URL` | (empty) | Base URL of the Prometheus/Thanos endpoint, e.g. `https://thanos-querier-openshift-monitoring.apps.acp.summit2026.com`. No trailing `/api/v1/...`. |
| `OCP_TOKEN`          | (empty) | Bearer token for Prometheus. Usually a ServiceAccount token with `cluster-reader` + `cluster-monitoring-view`. |
| `OCP_TLS_VERIFY`     | `false` | `true` to verify the Prometheus TLS cert. OCP's default cert is self-signed, so `false` is common for labs. |
| `OCP_NODE_NAMES`     | `node0,node1,arbiter` | Comma-separated list of node names to show. Must match the `node` label emitted by node-exporter. |
| `OCP_QUERY_TIMEOUT`  | `2.0`   | Seconds to wait for each query before giving up. |
| `OCP_CACHE_TTL`      | `10.0`  | Seconds to cache metrics between browser polls so we don't hammer Prometheus. |

Wiring up real metrics, example:

```sh
podman run ... \
  -e OCP_PROMETHEUS_URL="https://thanos-querier-openshift-monitoring.apps.acp.summit2026.com" \
  -e OCP_TOKEN="$(oc whoami -t)" \
  -e OCP_NODE_NAMES="node0,node1,arbiter" \
  inference-dashboard:dev
```

### Inference mechanics (unchanged from upstream)

These come from the original `inference-container/` and are untouched. Listed
here for completeness.

| Var | Default | Effect |
| --- | --- | --- |
| `MODEL_PATH`       | `/app/models/placards.onnx` | ONNX model location |
| `LABELS_PATH`      | `/app/models/labels.json`   | Label array; must include `none` |
| `CAMERA_INDEX`     | `0`    | Opens `/dev/video<N>` inside the container |
| `CAM_W` / `CAM_H`  | `640` / `480` | Capture resolution requested from V4L2 |
| `EXPOSURE`         | `-1`   | `-1` = auto, positive = manual exposure |
| `AUTOFOCUS`        | `-1`   | `-1` = leave alone, `0` = off, `1` = on |
| `FOCUS`            | `-1`   | `-1` = leave alone, `0-255` manual |
| `ARM_THRESHOLD`    | `0.85` | Minimum top-1 confidence to arm a trigger |
| `STABLE_FRAMES`    | `3`    | Consecutive identical predictions needed to fire |
| `COOLDOWN_SEC`     | `1.0`  | Minimum seconds between triggers |
| `NONE_MAX_PROB`    | `0.20` | Max probability of `none` class to allow arming |
| `MARGIN_MIN`       | `0.20` | Min gap between top-1 and top-2 confidence |
| `USE_PAPER_GATE`   | `true` | Require a bright-paper region before classifying |
| `BRIGHT_THRESH`    | `185`  | Grayscale threshold for the paper mask |
| `MIN_BRIGHT_FRAC`  | `0.18` | Min mask fraction that must be bright |
| `MAX_BRIGHT_FRAC`  | `0.92` | Max mask fraction (reject "all white" frames) |
| `MIN_CENTER_BRIGHT`| `0.12` | Min bright fraction in the center 50% of the frame |
| `DISPLAY_SIZE`     | `800`  | Pixel size of the square video in the MJPEG output |
| `WEB_PORT`         | `8080` | Port Flask listens on |
| `SHOW_DEBUG_ON_SCREEN` | `true` | Draw the top2/paper/fps row inside the MJPEG frame |
| `MQTT_ENABLED`     | `false` | `true` to publish triggers to MQTT |
| `MQTT_BROKER`      | `localhost` | MQTT broker hostname or IP |
| `MQTT_PORT`        | `1883` | MQTT broker port |
| `MQTT_TOPIC`       | `train/cmd` | Topic to publish command payloads on |


## Device / mount requirements

- `--device /dev/video<N>` — the USB camera. Remap to `/dev/video0` inside the
  container if the host's index differs: `--device /dev/video6:/dev/video0`.
- `--security-opt label=disable` — required on SELinux-enforcing hosts that
  don't ship the `container_video` SELinux module (i.e., anywhere other than
  the baked gateway bootc image).
- Port `8080/tcp` — publish with `-p 8080:8080` or whatever the deployment
  prefers.


## Quadlet / RHEM deployment

Drop into `/etc/containers/systemd/inference-dashboard.container` (or deliver
via RHEM):

```ini
[Unit]
Description=Edge AI Inference Dashboard
After=network-online.target
Wants=network-online.target

[Container]
Image=quay.io/<org>/inference-dashboard:v1
ContainerName=inference-dashboard
AddDevice=/dev/video0
PublishPort=8080:8080
SecurityLabelDisable=true
User=0

Environment=DEVICE_ID=gateway-01
Environment=SITE_TITLE_LEAD=Red Hat
Environment=SITE_TITLE=Edge AI Train Demo
Environment=SITE_SUBTITLE=Summit 2026 · OpenShift + Edge Manager
Environment=MQTT_ENABLED=true
Environment=MQTT_BROKER=mosquitto.train-demo.svc
Environment=MQTT_PORT=1883
Environment=MQTT_TOPIC=train/cmd
Environment=OCP_PROMETHEUS_URL=https://thanos-querier-openshift-monitoring.apps.acp.summit2026.com

[Service]
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

`systemctl daemon-reload && systemctl start inference-dashboard.service`.


## Tiling workflow (Ken-style)

For a 1080p desktop where you want to show the demo alongside a dashboard or
terminal, tile two browser windows:

- Left half:  `http://<host>:8080/feed`  — auto-scales to the window size
- Right half: `http://<host>:8080/logs`  — live inference log, no terminal needed

For a wall-mounted TV, just open `http://<host>:8080/` fullscreen.


## What's different from `../inference-container/`

- New files: `templates/dashboard.html`, `templates/feed.html`, `templates/logs.html`, `static/dashboard.css`, `static/redhat-logo.svg`, `README.md`
- `Containerfile` adds `COPY templates/` and `COPY static/`; label bumped to `1.1-dashboard`.
- `inference.py`:
  - Imports: `ssl`, `sys`, `urllib.*`, `deque`, `datetime`, `render_template`, `jsonify`, `request`
  - New block: stdout tee (`_StdoutTee`) that mirrors every `print()` into an in-memory ring for `/logs`
  - New block: status state sidecar (`_status_state`, `_recent_commands`, `publish_frame_status`, `publish_trigger`, `get_status_snapshot`)
  - New block: optional OCP Prometheus queries (`fetch_ocp_metrics`, gated on `OCP_PROMETHEUS_URL`)
  - New routes: `/feed`, `/logs`, `/api/status`, `/api/logs`
  - Replaced `/` to render `dashboard.html` instead of the inline 14-line HTML
  - Two call-sites added **inside** `inference_loop()`: one `publish_trigger()` next to the existing `TRIGGER!` print, one `publish_frame_status()` next to the existing `set_frame()`. No mechanics (camera, ONNX, paper gate, triggering, MQTT) changed.
