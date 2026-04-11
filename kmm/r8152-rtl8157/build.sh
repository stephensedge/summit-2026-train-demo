#!/bin/bash
# Build the r8152 v2.18.1 kernel module image with RTL8157 support
# Run on the bootstrap NUC where podman + Harbor access are available
set -euo pipefail

REGISTRY="${REGISTRY:-registry-registry.apps.bootstrap.summit2026.com}"
PROJECT="${PROJECT:-kmm}"
IMAGE_NAME="${IMAGE_NAME:-r8152-rtl8157}"
KERNEL_VERSION="${KERNEL_VERSION:-$(oc --kubeconfig=/root/acp-kubeconfig get nodes -o jsonpath='{.items[0].status.nodeInfo.kernelVersion}')}"
TAG_SUFFIX="${TAG_SUFFIX:-v2}"
DTK_IMAGE="${DTK_IMAGE:-$(oc --kubeconfig=/root/acp-kubeconfig adm release info --image-for=driver-toolkit --insecure)}"
HARBOR_PASSWORD="${HARBOR_PASSWORD:-R3dh4t123!}"

WORKDIR=$(mktemp -d)
trap "rm -rf $WORKDIR" EXIT

cd "$WORKDIR"
echo "=== Extracting r8152 v2.18.1 source ==="
tar xzf "$(dirname "$0")/r8152-v2.18.1.tar.gz"
mv realtek-r8152-linux-* r8152-src

echo "=== Patching for RHEL 9.6 (kernel 5.14 with newer APIs backported) ==="
cd r8152-src
sed -i 's|KERNEL_VERSION(5,15,0)|KERNEL_VERSION(5,14,0)|g; \
        s|KERNEL_VERSION(5,17,0)|KERNEL_VERSION(5,14,0)|g; \
        s|KERNEL_VERSION(6,9,0)|KERNEL_VERSION(5,14,0)|g; \
        s|KERNEL_VERSION(5,19,0)|KERNEL_VERSION(5,14,0)|g; \
        s|KERNEL_VERSION(6,4,10)|KERNEL_VERSION(5,14,0)|g' r8152.c compatibility.h

cd "$WORKDIR"
cp "$(dirname "$0")/Containerfile" .

echo "=== Logging in to Harbor ==="
podman login --tls-verify=false -u admin -p "$HARBOR_PASSWORD" "$REGISTRY"

IMAGE_TAG="$REGISTRY/$PROJECT/$IMAGE_NAME:${KERNEL_VERSION}-${TAG_SUFFIX}"
echo "=== Building $IMAGE_TAG ==="
podman build --tls-verify=false \
  --build-arg "DTK_AUTO=$DTK_IMAGE" \
  --build-arg "KERNEL_FULL_VERSION=$KERNEL_VERSION" \
  -t "$IMAGE_TAG" .

echo "=== Pushing $IMAGE_TAG ==="
podman push --tls-verify=false "$IMAGE_TAG"

echo "=== Done. Built and pushed: $IMAGE_TAG ==="
echo "Update the KMM Module CR's containerImage field to this tag if needed."
