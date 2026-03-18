#!/bin/bash
set -e

IMAGE_DIR="/usr/lib/conatiner-images"
echo "Starting image import..."

# Loop through our reference text files
for ref_file in "$IMAGE_DIR"/*.ref; do
    [ -f "$ref_file" ] || continue 
    
    # Get the matching tar file and the exact image string
    tar_file="${ref_file%.ref}.tar"
    image_ref=$(cat "$ref_file")
    
    echo "Loading $image_ref into local storage..."
    
    # Use skopeo to force it into CRI-O/Podman storage with the exact digest name
    if skopeo copy "docker-archive:$tar_file" "containers-storage:$image_ref"; then
        echo "Success: $image_ref"
    else
        echo "Failed to load $image_ref" >&2
        exit 1
    fi
done

echo "All images imported successfully."