To create an OCI artificat package (used by RHEM Software Catalog):

Create inference.container file:
cat > inference.container <<'EOF'
[Unit]
Description=Summit 2026 Train Demo Inference

[Container]
Image=quay.io/kenosborn/inference-train-demo:v2
ContainerName=inference-train-demo
User=0
AddDevice=/dev/video0
AddDevice=/dev/video1
SecurityLabelDisable=true
PublishPort=8080:8080
Environment=CAM_W=640
Environment=CAM_H=480
Environment=DISPLAY_SIZE=800
Environment=USE_PAPER_GATE=false
Environment=EXPOSURE=-1
Environment=MARGIN_MIN=0.50
Environment=STABLE_FRAMES=6
Environment=ARM_THRESHOLD=0.93
Environment=MQTT_ENABLED=false
Environment=COOLDOWN_SEC=3.0

[Service]
Restart=always

[Install]
WantedBy=default.target
EOF

podman artifact add quay.io/kenosborn/inference-quadlet:scv1 inference.container
podman artifact push quay.io/kenosborn/inference-quadlet:scv1

In the catalog item, call:
uri: quay.io/kenosborn/inference-quadlet:scv1
