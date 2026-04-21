sudo podman run --rm -e MQTT_PORT=11883 -e MQTT_BROKER=192.168.107.218 --device /dev/mtx_tty_mb:/dev/mtx_tty_mb -v /home/josh/control2.py:/opt/control/control.py:Z localhost/control:latest
