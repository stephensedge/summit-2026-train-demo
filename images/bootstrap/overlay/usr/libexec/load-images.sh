#!/bin/bash
set -e
IMAGE_DIR="/usr/lib/container-images"

echo "Starting image import..."

# ==========================================
# PHASE 1: Load strict digest images using 'dir:' transport
# ==========================================
echo "Checking for .ref digest payloads..."
for ref_file in "$IMAGE_DIR"/*.ref; do
    [ -f "$ref_file" ] || continue

    img_dir="${ref_file%.ref}"
    image_ref=$(cat "$ref_file")

    echo "Injecting $image_ref into local storage..."
    if [ ! -f "$img_dir/manifest.json" ]; then
        echo "WARNING: $image_ref missing manifest.json, skipping (will be pulled at runtime)" >&2
        continue
    fi
    if skopeo copy "dir:$img_dir" "containers-storage:$image_ref"; then
        echo "Success: $image_ref"
    else
        echo "WARNING: Failed to load $image_ref, skipping (will be pulled at runtime)" >&2
    fi
done

# ==========================================
# PHASE 2: Load standard tagged images (dhcp, dns, etc.)
# ==========================================
echo "Checking for remaining standard .tar archives..."
for tar_file in "$IMAGE_DIR"/*.tar; do
    [ -f "$tar_file" ] || continue

    echo "Loading standard archive $tar_file ..."
    if podman load -i "$tar_file"; then
        echo "Success: $tar_file"
    else
        echo "Failed to load standard archive $tar_file" >&2
        exit 1
    fi
done

echo "All images imported successfully."