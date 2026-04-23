# ---------------------------------------------------------------------------
# Last Update: 27-Mar-26
# ---------------------------------------------------------------------------

import json
import os
import ssl
import sys
import time
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime, timezone

import numpy as np
import cv2
import onnxruntime as ort
from flask import Flask, Response, jsonify, render_template, request

# ---------------------------------------------------------------------------
# Configuration — all values read from environment variables so the container
# can be tuned at runtime via the Quadlet unit without rebuilding the image.
# Defaults here match the original MacBook development values.
# ---------------------------------------------------------------------------

def _bool(key: str, default: bool) -> bool:
    """Parse a boolean env var accepting true/false/1/0 (case-insensitive)."""
    val = os.environ.get(key, "").strip().lower()
    if val in ("true", "1", "yes"):
        return True
    if val in ("false", "0", "no"):
        return False
    return default

MODEL_PATH  = os.environ.get("MODEL_PATH",  "/app/models/placards.onnx")
LABELS_PATH = os.environ.get("LABELS_PATH", "/app/models/labels.json")

CAM_INDEX   = int(os.environ.get("CAMERA_INDEX", "0"))
CAM_W       = int(os.environ.get("CAM_W", "640"))
CAM_H       = int(os.environ.get("CAM_H", "480"))
EXPOSURE    = int(os.environ.get("EXPOSURE",    "-1"))  # -1 = auto, positive = manual
AUTOFOCUS   = int(os.environ.get("AUTOFOCUS",   "-1"))  # -1 = don't touch, 1=on, 0=off
FOCUS       = int(os.environ.get("FOCUS",       "-1"))  # -1 = don't touch, 0-255 manual
CONTRAST    = int(os.environ.get("CONTRAST",    "-1"))  # -1 = don't touch, 0-255
BRIGHTNESS  = int(os.environ.get("BRIGHTNESS",  "-1"))  # -1 = don't touch, 0-255
SATURATION  = int(os.environ.get("SATURATION",  "-1"))  # -1 = don't touch, 0-255
SHARPNESS   = int(os.environ.get("SHARPNESS",   "-1"))  # -1 = don't touch, 0-255
GAIN        = int(os.environ.get("GAIN",        "-1"))  # -1 = don't touch, 0-255
IN_W, IN_H  = 224, 224  # model input size — fixed by training, not tunable

DISPLAY_SIZE = int(os.environ.get("DISPLAY_SIZE", "800"))
WEB_PORT     = int(os.environ.get("WEB_PORT", "8080"))

# --- Safety / arming knobs ---
ALLOWED_COMMANDS = {"start", "stop", "slow", "reverse"}

ARM_THRESHOLD = float(os.environ.get("ARM_THRESHOLD", "0.85"))
STABLE_FRAMES = int(os.environ.get("STABLE_FRAMES",  "3"))
COOLDOWN_SEC  = float(os.environ.get("COOLDOWN_SEC", "1.0"))

NONE_MAX_PROB = float(os.environ.get("NONE_MAX_PROB", "0.20"))
MARGIN_MIN    = float(os.environ.get("MARGIN_MIN",    "0.20"))

# --- Bright paper gate ---
USE_PAPER_GATE    = _bool("USE_PAPER_GATE", True)
MIN_BRIGHT_FRAC   = float(os.environ.get("MIN_BRIGHT_FRAC",   "0.18"))
MAX_BRIGHT_FRAC   = float(os.environ.get("MAX_BRIGHT_FRAC",   "0.92"))
MIN_CENTER_BRIGHT = float(os.environ.get("MIN_CENTER_BRIGHT", "0.12"))
BRIGHT_THRESH     = int(os.environ.get("BRIGHT_THRESH",       "185"))

PRINT_EVERY_SEC      = float(os.environ.get("PRINT_EVERY_SEC",   "0.20"))
DRAW_CROP_GUIDE      = _bool("DRAW_CROP_GUIDE",     True)
TRIGGER_FLASH_SEC    = float(os.environ.get("TRIGGER_FLASH_SEC", "0.90"))
SHOW_DEBUG_ON_SCREEN = _bool("SHOW_DEBUG_ON_SCREEN", True)

# --- MQTT ---
MQTT_ENABLED  = _bool("MQTT_ENABLED", False)
MQTT_BROKER   = os.environ.get("MQTT_BROKER",  "localhost")
MQTT_PORT     = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_TOPIC    = os.environ.get("MQTT_TOPIC",   "train/cmd")
DEVICE_ID     = os.environ.get("DEVICE_ID",    "ms01-camera")
MODEL_VERSION = os.environ.get("MODEL_VERSION", "placards-v1")

# --- Dashboard branding (shown in /) ---
SITE_TITLE      = os.environ.get("SITE_TITLE",      "Edge AI Train Demo")
SITE_SUBTITLE   = os.environ.get("SITE_SUBTITLE",   "Summit 2026 · OpenShift + Edge Manager")
SITE_TITLE_LEAD = os.environ.get("SITE_TITLE_LEAD", "Red Hat")

# ---------------------------------------------------------------------------
# Shared frame buffer — inference loop writes, Flask thread reads
# ---------------------------------------------------------------------------
_frame_lock   = threading.Lock()
_latest_frame = None  # JPEG bytes


def set_frame(jpeg_bytes):
    global _latest_frame
    with _frame_lock:
        _latest_frame = jpeg_bytes


def get_frame():
    with _frame_lock:
        return _latest_frame


# ---------------------------------------------------------------------------
# Stdout tee — mirror every print() from the inference loop into an in-memory
# ring buffer so the browser "Live Log" view can show the same text that
# `podman logs -f` / `journalctl -u … -f` would show. The wrapped stdout is
# installed once at import time and never swapped back. No print() call in
# the inference loop changes — this is pure observability.
# ---------------------------------------------------------------------------
LOG_RING_SIZE = int(os.environ.get("LOG_RING_SIZE", "500"))

class _StdoutTee:
    def __init__(self, original):
        self._orig = original
        self._buf  = deque(maxlen=LOG_RING_SIZE)
        self._lock = threading.Lock()
        self._seq  = 0

    def write(self, data):
        self._orig.write(data)
        if not data:
            return
        for line in data.splitlines():
            if not line.strip():
                continue
            with self._lock:
                self._seq += 1
                self._buf.append({
                    "seq":  self._seq,
                    "ts":   datetime.now(timezone.utc).isoformat(),
                    "line": line,
                })

    def flush(self):
        self._orig.flush()

    def snapshot(self, after_seq=0, limit=200):
        with self._lock:
            out = [e for e in self._buf if e["seq"] > after_seq]
        return out[-limit:]


_stdout_tee = _StdoutTee(sys.stdout)
sys.stdout = _stdout_tee


# ---------------------------------------------------------------------------
# Dashboard state — observability sidecar. The inference loop writes the
# current per-frame snapshot plus an append-only ring of trigger events;
# the Flask /api/status route reads it. No path in inference depends on
# these values — they are pure observability.
# ---------------------------------------------------------------------------
STARTED_AT = datetime.now(timezone.utc)
RECENT_LIMIT = int(os.environ.get("RECENT_LIMIT", "10"))

_status_lock = threading.Lock()
_status_state = {
    "label": "none",
    "confidence": 0.0,
    "armed": False,
    "paper": False,
    "fps": 0.0,
    "streak": 0,
    "margin": 0.0,
    "none_prob": 1.0,
    "frame_count": 0,
    "last_update": None,
}
_recent_commands = deque(maxlen=RECENT_LIMIT)

# Longer trigger history for the activity sparkline. Each entry is an ISO
# timestamp + label; the frontend buckets these into time bins for the chart.
ACTIVITY_WINDOW_SEC = int(os.environ.get("ACTIVITY_WINDOW_SEC", "300"))
_trigger_history = deque(maxlen=1000)


def publish_frame_status(**fields):
    with _status_lock:
        _status_state.update(fields)
        _status_state["last_update"] = datetime.now(timezone.utc).isoformat()
        _status_state["frame_count"] = _status_state.get("frame_count", 0) + 1


def publish_trigger(label: str, confidence: float):
    now = datetime.now(timezone.utc)
    with _status_lock:
        entry = {
            "label":      label,
            "confidence": round(float(confidence), 3),
            "ts":         now.isoformat(),
        }
        _recent_commands.appendleft(entry)
        _trigger_history.append({"ts": entry["ts"], "label": label})


def get_status_snapshot():
    with _status_lock:
        # Drop trigger-history entries older than the activity window
        cutoff = (datetime.now(timezone.utc).timestamp() - ACTIVITY_WINDOW_SEC)
        activity = [
            t for t in _trigger_history
            if datetime.fromisoformat(t["ts"]).timestamp() >= cutoff
        ]
        return dict(_status_state), list(_recent_commands), activity


# ---------------------------------------------------------------------------
# Optional OCP metrics — if OCP_PROMETHEUS_URL is set, query Thanos/Prometheus
# for per-node CPU, memory, and temperature. Any error (unreachable, auth,
# query failure) returns an "unavailable" payload — never raises into Flask.
# ---------------------------------------------------------------------------
OCP_PROMETHEUS_URL = os.environ.get("OCP_PROMETHEUS_URL", "").rstrip("/")
OCP_TOKEN          = os.environ.get("OCP_TOKEN", "")
OCP_TLS_VERIFY     = _bool("OCP_TLS_VERIFY", False)
OCP_NODE_NAMES     = [n.strip() for n in os.environ.get(
    "OCP_NODE_NAMES", "node0,node1,arbiter").split(",") if n.strip()]
OCP_QUERY_TIMEOUT  = float(os.environ.get("OCP_QUERY_TIMEOUT", "2.0"))

_ocp_cache_lock = threading.Lock()
_ocp_cache      = {"data": None, "fetched": 0.0}
OCP_CACHE_TTL   = float(os.environ.get("OCP_CACHE_TTL", "10.0"))

# Train telemetry — voltage / register / raw pushed by the `control` container
# to the Prometheus pushgateway. We read the pushgateway directly (no OCP
# Prometheus involvement needed) so the panel works the moment the control
# container starts publishing, regardless of ServiceMonitor configuration.
PUSHGATEWAY_URL        = os.environ.get("PUSHGATEWAY_URL", "").rstrip("/")
PUSHGATEWAY_TIMEOUT    = float(os.environ.get("PUSHGATEWAY_TIMEOUT", "2.0"))
TRAIN_MAX_VOLTAGE      = float(os.environ.get("TRAIN_MAX_VOLTAGE", "10.3"))
_train_cache_lock = threading.Lock()
_train_cache      = {"data": None, "fetched": 0.0}
TRAIN_CACHE_TTL   = float(os.environ.get("TRAIN_CACHE_TTL", "2.0"))


def _parse_prom_text(body: str):
    """Tiny Prometheus text-format parser. Returns list of (name, labels, value)."""
    out = []
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # split name{labels} value
        if "{" in line:
            name, rest = line.split("{", 1)
            labels_s, rest = rest.split("}", 1)
            value_s = rest.strip().split()[0]
            labels = {}
            for pair in labels_s.split(","):
                if "=" not in pair:
                    continue
                k, v = pair.split("=", 1)
                labels[k.strip()] = v.strip().strip('"')
        else:
            parts = line.split()
            if len(parts) < 2:
                continue
            name, value_s = parts[0], parts[1]
            labels = {}
        try:
            value = float(value_s)
        except ValueError:
            continue
        out.append((name, labels, value))
    return out


def fetch_train_metrics():
    now = time.time()
    with _train_cache_lock:
        if _train_cache["data"] and (now - _train_cache["fetched"]) < TRAIN_CACHE_TTL:
            return _train_cache["data"]

    if not PUSHGATEWAY_URL:
        data = {"available": False, "reason": "PUSHGATEWAY_URL not set"}
        with _train_cache_lock:
            _train_cache.update(data=data, fetched=now)
        return data

    try:
        req = urllib.request.Request(PUSHGATEWAY_URL + "/metrics")
        with urllib.request.urlopen(req, timeout=PUSHGATEWAY_TIMEOUT) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        parsed = _parse_prom_text(body)

        # Support both schemas:
        #   Old (AO0_output job):      voltage{output="ao0"}
        #   New (motor_controller job): voltage{output="ao0_speed"}, voltage{output="ao1_dir"}, direction
        speed_v = dir_v = dir_gauge = None
        speed_raw = dir_raw = None
        for name, labels, value in parsed:
            job    = labels.get("job", "")
            output = labels.get("output", "")
            if name == "voltage":
                if output in ("ao0", "ao0_speed"):
                    speed_v = value
                elif output == "ao1_dir":
                    dir_v = value
            elif name == "raw_value":
                if output in ("ao0", "ao0_speed"):
                    speed_raw = value
                elif output == "ao1_dir":
                    dir_raw = value
            elif name == "direction":
                dir_gauge = value

        # Compute PWM % the same way the Arduino does:
        #   Arduino reads IONA analog in via 10-bit ADC (0..1023), then
        #   map(raw, 0, 1023, 0, 255) for 8-bit PWM. Magnitude / max_v % matches.
        pwm_pct = None
        if speed_v is not None:
            pwm_pct = max(0.0, min(100.0, (abs(speed_v) / TRAIN_MAX_VOLTAGE) * 100.0))

        # Direction preference: explicit `direction` gauge first, then ao1_dir voltage
        direction = None
        if dir_gauge is not None:
            direction = "forward" if dir_gauge >= 0 else "reverse"
        elif dir_v is not None:
            direction = "reverse" if dir_v >= (TRAIN_MAX_VOLTAGE / 2.0) else "forward"

        # State: stopped when PWM ~ 0, else running (with direction)
        if pwm_pct is None:
            state = "unknown"
        elif pwm_pct < 1.0:
            state = "stopped"
        else:
            state = "running"

        data = {
            "available":      True,
            "voltage":        speed_v,
            "speed_voltage":  speed_v,
            "dir_voltage":    dir_v,
            "power_pct":      pwm_pct,
            "pwm_pct":        pwm_pct,
            "max_voltage":    TRAIN_MAX_VOLTAGE,
            "direction":      direction,
            "raw_value":      speed_raw,
            "dir_raw_value":  dir_raw,
            "state":          state,
        }
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        data = {"available": False, "reason": f"pushgateway unreachable: {exc}"}
    with _train_cache_lock:
        _train_cache.update(data=data, fetched=now)
    return data


def _prom_query(expr: str):
    if not OCP_PROMETHEUS_URL:
        return None
    url = f"{OCP_PROMETHEUS_URL}/api/v1/query?query={urllib.parse.quote(expr)}"
    req = urllib.request.Request(url)
    if OCP_TOKEN:
        req.add_header("Authorization", f"Bearer {OCP_TOKEN}")
    ctx = ssl.create_default_context()
    if not OCP_TLS_VERIFY:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, timeout=OCP_QUERY_TIMEOUT, context=ctx) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    if body.get("status") != "success":
        return None
    return body["data"]["result"]


def _prom_series_by_instance(result):
    """Flatten Prometheus vector result to {instance_or_node: value}."""
    out = {}
    if not result:
        return out
    for item in result:
        metric = item.get("metric", {})
        key = metric.get("node") or metric.get("instance") or metric.get("kubernetes_node") or ""
        val = item.get("value", [None, None])[1]
        try:
            out[key] = float(val)
        except (TypeError, ValueError):
            pass
    return out


def _match_node(series: dict, name: str):
    """Best-effort match of a node name to a Prometheus series key."""
    if name in series:
        return series[name]
    for key, val in series.items():
        if key.startswith(name) or name in key:
            return val
    return None


def fetch_ocp_metrics():
    now = time.time()
    with _ocp_cache_lock:
        if _ocp_cache["data"] and (now - _ocp_cache["fetched"]) < OCP_CACHE_TTL:
            return _ocp_cache["data"]

    if not OCP_PROMETHEUS_URL:
        data = {"available": False, "reason": "OCP_PROMETHEUS_URL not set",
                "nodes": [{"name": n} for n in OCP_NODE_NAMES]}
        with _ocp_cache_lock:
            _ocp_cache.update(data=data, fetched=now)
        return data

    try:
        cpu = _prom_series_by_instance(_prom_query(
            '100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[1m])) * 100)'))
        mem = _prom_series_by_instance(_prom_query(
            '100 * (1 - sum by (instance) (node_memory_MemAvailable_bytes) '
            '/ sum by (instance) (node_memory_MemTotal_bytes))'))
        temp = _prom_series_by_instance(_prom_query(
            'max by (instance) (node_hwmon_temp_celsius)'))

        # Per-node filesystem (/var — covers OS + containers + Portworx metadata)
        disk_size  = _prom_series_by_instance(_prom_query(
            'sum by (instance) (node_filesystem_size_bytes{mountpoint="/var"})'))
        disk_avail = _prom_series_by_instance(_prom_query(
            'sum by (instance) (node_filesystem_avail_bytes{mountpoint="/var"})'))

        # Hostname + internal IP + role from kube-state-metrics.
        # kube_node_info exposes: node, internal_ip, kernel_version, os_image, ...
        # kube_node_role exposes: node, role (master, worker, arbiter, ...)
        info_map, role_map = {}, {}
        info_raw = _prom_query("kube_node_info")
        if info_raw:
            for item in info_raw:
                m = item.get("metric", {})
                n = m.get("node")
                if n:
                    info_map[n] = {
                        "internal_ip": m.get("internal_ip"),
                        "kernel":      m.get("kernel_version"),
                        "os":          m.get("os_image"),
                    }
        role_raw = _prom_query("kube_node_role")
        if role_raw:
            for item in role_raw:
                m = item.get("metric", {})
                n = m.get("node")
                r = m.get("role")
                if n and r:
                    role_map.setdefault(n, []).append(r)

        nodes = []
        total_disk = used_disk = 0.0
        for name in OCP_NODE_NAMES:
            info  = info_map.get(name, {})
            roles = role_map.get(name, [])
            # prefer the more specific role (master/arbiter > control-plane > worker)
            rank = {"arbiter": 0, "master": 1, "control-plane": 2, "worker": 3}
            roles.sort(key=lambda r: rank.get(r, 9))
            ds = _match_node(disk_size,  name)
            da = _match_node(disk_avail, name)
            disk_pct = None
            disk_used_gb = None
            disk_total_gb = None
            if ds is not None and da is not None and ds > 0:
                used = ds - da
                disk_pct = max(0.0, min(100.0, (used / ds) * 100.0))
                disk_used_gb  = round(used / 1e9, 1)
                disk_total_gb = round(ds   / 1e9, 1)
                total_disk += ds
                used_disk  += used
            nodes.append({
                "name":          name,
                "cpu_pct":       _match_node(cpu,  name),
                "mem_pct":       _match_node(mem,  name),
                "temp_c":        _match_node(temp, name),
                "disk_pct":      disk_pct,
                "disk_used_gb":  disk_used_gb,
                "disk_total_gb": disk_total_gb,
                "internal_ip":   info.get("internal_ip"),
                "role":          roles[0] if roles else None,
            })
        data = {
            "available":       True,
            "nodes":           nodes,
            "storage_total_gb": round(total_disk / 1e9, 1) if total_disk else None,
            "storage_used_gb":  round(used_disk  / 1e9, 1) if total_disk else None,
            "storage_pct":      round((used_disk / total_disk) * 100.0, 1) if total_disk else None,
        }
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        data = {"available": False, "reason": f"query failed: {exc}",
                "nodes": [{"name": n} for n in OCP_NODE_NAMES]}
    with _ocp_cache_lock:
        _ocp_cache.update(data=data, fetched=now)
    return data


# ---------------------------------------------------------------------------
# Flask MJPEG server
# ---------------------------------------------------------------------------
app = Flask(__name__, template_folder="templates", static_folder="static")


@app.route("/")
def index():
    return render_template(
        "dashboard.html",
        device_id=DEVICE_ID,
        model_version=MODEL_VERSION,
        mqtt_broker=MQTT_BROKER,
        mqtt_enabled=MQTT_ENABLED,
        started_at=STARTED_AT.isoformat(),
        site_title=SITE_TITLE,
        site_subtitle=SITE_SUBTITLE,
        site_title_lead=SITE_TITLE_LEAD,
    )


@app.route("/feed")
def feed():
    return render_template("feed.html", device_id=DEVICE_ID)


@app.route("/logs")
def logs():
    return render_template("logs.html", device_id=DEVICE_ID)


@app.route("/api/logs")
def api_logs():
    try:
        since = int(request.args.get("since", "0"))
    except ValueError:
        since = 0
    try:
        limit = max(1, min(500, int(request.args.get("limit", "200"))))
    except ValueError:
        limit = 200
    entries = _stdout_tee.snapshot(after_seq=since, limit=limit)
    last_seq = entries[-1]["seq"] if entries else since
    return jsonify({"entries": entries, "last_seq": last_seq})


@app.route("/api/status")
def api_status():
    state, recent, activity = get_status_snapshot()
    ocp = fetch_ocp_metrics()
    return jsonify({
        "device_id":     DEVICE_ID,
        "model_version": MODEL_VERSION,
        "started_at":    STARTED_AT.isoformat(),
        "now":           datetime.now(timezone.utc).isoformat(),
        "mqtt": {
            "enabled": MQTT_ENABLED,
            "broker":  MQTT_BROKER,
            "port":    MQTT_PORT,
            "topic":   MQTT_TOPIC,
        },
        "inference": state,
        "recent":    recent,
        "activity":  {"triggers": activity, "window_sec": ACTIVITY_WINDOW_SEC},
        "ocp":       ocp,
        "train":     fetch_train_metrics(),
    })


@app.route("/stream")
def stream():
    def generate():
        while True:
            frame = get_frame()
            if frame is not None:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                )
            time.sleep(0.033)  # ~30fps max to client
    return Response(
        generate(),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )


# Camera-only view: crops the baked-in bottom status panel off the JPEG so
# the dashboard can show a square camera feed that fills more of its column.
# Cached by "last source bytes" so multiple viewers share one crop per frame.
_camera_jpeg_lock = threading.Lock()
_camera_jpeg     = {"src": None, "data": None}


def get_camera_only_frame():
    full = get_frame()
    if full is None:
        return None
    with _camera_jpeg_lock:
        if _camera_jpeg["src"] is full and _camera_jpeg["data"] is not None:
            return _camera_jpeg["data"]
    # Decode, crop to top square, re-encode
    arr = np.frombuffer(full, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return None
    h, w = img.shape[:2]
    size = min(h, w)
    square = img[:size, :size]
    ok, jpeg = cv2.imencode(".jpg", square, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        return None
    data = jpeg.tobytes()
    with _camera_jpeg_lock:
        _camera_jpeg["src"]  = full
        _camera_jpeg["data"] = data
    return data


@app.route("/camera-stream")
def camera_stream():
    def generate():
        while True:
            frame = get_camera_only_frame()
            if frame is not None:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                )
            time.sleep(0.033)
    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")


# ---------------------------------------------------------------------------
# Inference helpers — identical to inference.py
# ---------------------------------------------------------------------------

def softmax(x):
    e = np.exp(x - np.max(x))
    return e / e.sum()


def center_square_crop(frame_bgr):
    h, w = frame_bgr.shape[:2]
    side = min(h, w)
    y0 = (h - side) // 2
    x0 = (w - side) // 2
    crop = frame_bgr[y0:y0 + side, x0:x0 + side]
    return crop, (x0, y0, side)


def preprocess_rgb(rgb):
    rgb = cv2.resize(rgb, (IN_W, IN_H), interpolation=cv2.INTER_AREA)
    x = rgb.astype(np.float32) / 255.0
    x = np.transpose(x, (2, 0, 1))
    x = np.expand_dims(x, axis=0)
    return x


def detect_bright_paper(square_bgr):
    gray = cv2.cvtColor(square_bgr, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    _, mask = cv2.threshold(blur, BRIGHT_THRESH, 255, cv2.THRESH_BINARY)
    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    bright_frac = float(np.count_nonzero(mask)) / mask.size
    h, w = mask.shape[:2]
    y0, y1 = int(h * 0.25), int(h * 0.75)
    x0, x1 = int(w * 0.25), int(w * 0.75)
    center = mask[y0:y1, x0:x1]
    center_bright_frac = float(np.count_nonzero(center)) / center.size
    found = (
        bright_frac >= MIN_BRIGHT_FRAC and
        bright_frac <= MAX_BRIGHT_FRAC and
        center_bright_frac >= MIN_CENTER_BRIGHT
    )
    return found, mask, bright_frac, center_bright_frac


def command_label_text(label: str) -> str:
    return label.upper()


def draw_text_with_bg(img, text, org, font_scale=1.0, text_color=(255, 255, 255),
                      bg_color=(0, 0, 0), thickness=2, pad=8):
    font = cv2.FONT_HERSHEY_SIMPLEX
    (tw, th), baseline = cv2.getTextSize(text, font, font_scale, thickness)
    x, y = org
    cv2.rectangle(
        img,
        (x - pad, y - th - pad),
        (x + tw + pad, y + baseline + pad),
        bg_color,
        -1,
    )
    cv2.putText(img, text, (x, y), font, font_scale, text_color, thickness, cv2.LINE_AA)


# ---------------------------------------------------------------------------
# Main inference loop
# ---------------------------------------------------------------------------

def inference_loop():
    with open(LABELS_PATH) as f:
        labels = json.load(f)

    if "none" not in labels:
        raise SystemExit("labels.json does not contain 'none' class.")
    none_idx = labels.index("none")

    sess = ort.InferenceSession(MODEL_PATH, providers=["CPUExecutionProvider"])
    input_name = sess.get_inputs()[0].name

    cap = cv2.VideoCapture(CAM_INDEX, cv2.CAP_V4L2)
    if not cap.isOpened():
        raise SystemExit("Could not open webcam. Try CAM_INDEX=1.")

    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAM_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_H)
    cap.set(cv2.CAP_PROP_FPS, 30)
    if EXPOSURE > 0:
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1)  # 1 = manual mode
        cap.set(cv2.CAP_PROP_EXPOSURE, EXPOSURE)
        print(f"Camera exposure: manual ({EXPOSURE})")
    else:
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 3)  # 3 = auto mode
        print("Camera exposure: auto")

    if AUTOFOCUS >= 0:
        cap.set(cv2.CAP_PROP_AUTOFOCUS, AUTOFOCUS)
        print(f"Camera autofocus: {'on' if AUTOFOCUS == 1 else 'off'}")
    if FOCUS >= 0:
        cap.set(cv2.CAP_PROP_FOCUS, FOCUS)
        print(f"Camera focus: {FOCUS}")
    if CONTRAST >= 0:
        cap.set(cv2.CAP_PROP_CONTRAST, CONTRAST)
        print(f"Camera contrast: {CONTRAST}")
    if BRIGHTNESS >= 0:
        cap.set(cv2.CAP_PROP_BRIGHTNESS, BRIGHTNESS)
        print(f"Camera brightness: {BRIGHTNESS}")
    if SATURATION >= 0:
        cap.set(cv2.CAP_PROP_SATURATION, SATURATION)
        print(f"Camera saturation: {SATURATION}")
    if SHARPNESS >= 0:
        cap.set(cv2.CAP_PROP_SHARPNESS, SHARPNESS)
        print(f"Camera sharpness: {SHARPNESS}")
    if GAIN >= 0:
        cap.set(cv2.CAP_PROP_GAIN, GAIN)
        print(f"Camera gain: {GAIN}")

    last_print = 0.0
    streak_label = None
    streak = 0
    last_trigger_time = 0.0
    last_trigger_label = None
    last_trigger_display_until = 0.0

    fps_t0 = time.time()
    fps_frames = 0
    fps_val = 0.0

    status_h = 300

    gate_status = "paper gate ON" if USE_PAPER_GATE else "paper gate OFF"
    print(f"Running ARMED webcam inference [{gate_status}]. Web stream on :{WEB_PORT}")
    print(
        f"ARM_THRESHOLD={ARM_THRESHOLD}  STABLE_FRAMES={STABLE_FRAMES}  "
        f"COOLDOWN_SEC={COOLDOWN_SEC}"
    )
    print(
        f"USE_PAPER_GATE={USE_PAPER_GATE}  BRIGHT_THRESH={BRIGHT_THRESH}  "
        f"MIN_BRIGHT_FRAC={MIN_BRIGHT_FRAC}  MIN_CENTER_BRIGHT={MIN_CENTER_BRIGHT}"
    )

    while True:
        ok, frame = cap.read()
        if not ok:
            print("Failed to read frame.")
            break

        now = time.time()

        square, (gx, gy, gside) = center_square_crop(frame)

        paper_found = True
        paper_mask = None
        bright_frac = 0.0
        center_bright_frac = 0.0

        if USE_PAPER_GATE:
            paper_found, paper_mask, bright_frac, center_bright_frac = \
                detect_bright_paper(square)

        if paper_found:
            rgb = cv2.cvtColor(square, cv2.COLOR_BGR2RGB)
            x = preprocess_rgb(rgb)
            logits = sess.run(None, {input_name: x})[0][0]
            probs = softmax(logits)
        else:
            probs = np.zeros(len(labels), dtype=np.float32)
            probs[none_idx] = 1.0

        top2 = np.argsort(probs)[::-1][:2]
        i1, i2 = int(top2[0]), int(top2[1])
        label1, conf1 = labels[i1], float(probs[i1])
        label2, conf2 = labels[i2], float(probs[i2])

        none_prob = float(probs[none_idx])
        margin = conf1 - conf2

        frame_armed = (
            paper_found and
            (label1 in ALLOWED_COMMANDS) and
            (conf1 >= ARM_THRESHOLD) and
            (none_prob <= NONE_MAX_PROB) and
            (margin >= MARGIN_MIN)
        )

        if frame_armed:
            if label1 == streak_label:
                streak += 1
            else:
                streak_label = label1
                streak = 1
        else:
            streak_label = None
            streak = 0

        triggered = False
        trigger_label = None

        if streak >= STABLE_FRAMES and (now - last_trigger_time) >= COOLDOWN_SEC:
            triggered = True
            trigger_label = streak_label
            last_trigger_time = now
            last_trigger_label = trigger_label
            last_trigger_display_until = now + TRIGGER_FLASH_SEC
            print(f"\n########## TRIGGER! {trigger_label.upper()} ##########\n", flush=True)
            publish_trigger(trigger_label, conf1)

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

            streak_label = None
            streak = 0

        # FPS
        fps_frames += 1
        if fps_frames >= 15:
            dt = time.time() - fps_t0
            fps_val = fps_frames / max(dt, 1e-6)
            fps_t0 = time.time()
            fps_frames = 0

        # Terminal logging
        if now - last_print >= PRINT_EVERY_SEC:
            status = "ARMED" if frame_armed else "idle "
            trig_txt = f"TRIGGER! {trigger_label}" if triggered else ""
            print(
                f"{label1:8s} conf={conf1:.3f}  "
                f"top2={label2}:{conf2:.3f}  "
                f"none={none_prob:.3f}  margin={margin:.3f}  "
                f"paper={'yes' if paper_found else 'no '}  "
                f"bright={bright_frac:.3f} center={center_bright_frac:.3f}  "
                f"fps~{fps_val:4.1f}  {status}  streak={streak}  {trig_txt}"
            )
            last_print = now

        # ── Build canvas — identical layout to inference.py ──────────────────
        h_frame, w_frame = frame.shape[:2]
        feed_size    = min(h_frame, w_frame)
        canvas_w     = DISPLAY_SIZE
        canvas_h     = DISPLAY_SIZE + status_h
        canvas       = np.zeros((canvas_h, canvas_w, 3), dtype=np.uint8)

        # Center-crop frame to square then scale to DISPLAY_SIZE
        x0_crop     = max(0, (w_frame - feed_size) // 2)
        y0_crop     = max(0, (h_frame - feed_size) // 2)
        feed_w      = min(feed_size, w_frame)
        feed_h      = min(feed_size, h_frame)
        feed_square = frame[y0_crop:y0_crop + feed_h, x0_crop:x0_crop + feed_w]
        feed_scaled = cv2.resize(feed_square, (DISPLAY_SIZE, DISPLAY_SIZE),
                                 interpolation=cv2.INTER_LINEAR)
        canvas[:DISPLAY_SIZE, :] = feed_scaled

        # Guide box coords scaled to DISPLAY_SIZE
        scale      = DISPLAY_SIZE / feed_size
        gbx        = int((gx - x0_crop) * scale)
        gby        = int((gy - y0_crop) * scale)
        gside_disp = int(gside * scale)

        # Paper gate mask preview
        if USE_PAPER_GATE and paper_mask is not None:
            preview_size = 120
            mask_small = cv2.resize(paper_mask, (preview_size, preview_size),
                                    interpolation=cv2.INTER_NEAREST)
            mask_small = cv2.cvtColor(mask_small, cv2.COLOR_GRAY2BGR)
            px = 8
            py = DISPLAY_SIZE - preview_size - 8
            canvas[py:py + preview_size, px:px + preview_size] = mask_small
            cv2.rectangle(canvas, (px, py), (px + preview_size, py + preview_size),
                          (255, 255, 255), 1)
            draw_text_with_bg(canvas, "paper gate", (px + 4, py + 16),
                font_scale=0.45, text_color=(255, 255, 255),
                bg_color=(0, 0, 0), thickness=1, pad=3)

        # Guide box color
        box_color = (255, 255, 255)
        if now < last_trigger_display_until:
            box_color = (0, 255, 0)
        elif frame_armed:
            box_color = (0, 255, 255)

        if DRAW_CROP_GUIDE:
            cv2.rectangle(canvas, (gbx, gby), (gbx + gside_disp, gby + gside_disp), box_color, 3)

        if USE_PAPER_GATE:
            inner_color = (0, 180, 0) if paper_found else (0, 0, 180)
            inset = 12
            cv2.rectangle(
                canvas,
                (gbx + inset, gby + inset),
                (gbx + gside_disp - inset, gby + gside_disp - inset),
                inner_color, 2
            )

        # Status panel
        panel_y = DISPLAY_SIZE
        cv2.line(canvas, (0, panel_y), (canvas_w, panel_y), (60, 60, 60), 2)

        if now < last_trigger_display_until and last_trigger_label is not None:
            status_text  = "COMMAND SENT:"
            cmd_text     = command_label_text(last_trigger_label)
            status_color = (0, 255, 0)
        elif frame_armed:
            status_text  = "READY:"
            cmd_text     = command_label_text(label1)
            status_color = (0, 255, 255)
        else:
            status_text  = "PREDICTION:"
            cmd_text     = command_label_text(label1)
            status_color = (255, 255, 255)

        font = cv2.FONT_HERSHEY_SIMPLEX
        for txt, fs, thick, yoff, color in [
            (status_text,               0.9, 2,  50,  status_color),
            (cmd_text,                  2.0, 4,  130, status_color),
            (f"Confidence: {conf1:.0%}", 0.9, 2, 185, (200, 200, 200)),
        ]:
            (tw, _), _ = cv2.getTextSize(txt, font, fs, thick)
            cx = (canvas_w - tw) // 2
            draw_text_with_bg(canvas, txt, (cx, panel_y + yoff),
                font_scale=fs, text_color=color, bg_color=(0, 0, 0),
                thickness=thick, pad=6)

        if SHOW_DEBUG_ON_SCREEN:
            debug_lines = [
                f"top2: {label2} {conf2:.3f}   |   none: {none_prob:.3f}   |   margin: {margin:.3f}",
                f"streak: {streak}   |   paper: {'off' if not USE_PAPER_GATE else ('yes' if paper_found else 'no')}   |   bright: {bright_frac:.3f}/{center_bright_frac:.3f}   |   fps: {fps_val:.1f}",
            ]
            for i, line in enumerate(debug_lines):
                (tw, _), _ = cv2.getTextSize(line, font, 0.52, 1)
                cx = (canvas_w - tw) // 2
                draw_text_with_bg(canvas, line, (cx, panel_y + 220 + i * 32),
                    font_scale=0.52, text_color=(160, 160, 160),
                    bg_color=(0, 0, 0), thickness=1, pad=3)

        # Encode canvas as JPEG and push to shared frame buffer
        _, jpeg = cv2.imencode(".jpg", canvas, [cv2.IMWRITE_JPEG_QUALITY, 85])
        set_frame(jpeg.tobytes())

        publish_frame_status(
            label=label1,
            confidence=round(float(conf1), 3),
            top2_label=label2,
            top2_confidence=round(float(conf2), 3),
            armed=bool(frame_armed),
            paper=bool(paper_found) if USE_PAPER_GATE else True,
            fps=round(float(fps_val), 1),
            streak=int(streak),
            margin=round(float(margin), 3),
            none_prob=round(float(none_prob), 3),
            bright_frac=round(float(bright_frac), 3),
            center_bright_frac=round(float(center_bright_frac), 3),
            use_paper_gate=bool(USE_PAPER_GATE),
        )

    cap.release()


# ---------------------------------------------------------------------------
# Entry point — start inference in background thread, Flask in foreground
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    t = threading.Thread(target=inference_loop, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=WEB_PORT, threaded=True)