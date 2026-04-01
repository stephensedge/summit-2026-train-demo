#!/bin/bash

# Resolve all paths to absolute before we cd anywhere
CONTAINER_IMAGE="$1"
KICKSTART="$(realpath "$2")"
BOOT_ISO="$(realpath "$3")"
OUTPUT_ISO="$4"

TEMPDIR=$(mktemp --directory)

echo "Unpack container image"
mkdir -p "${TEMPDIR}/container"
skopeo copy "containers-storage:${CONTAINER_IMAGE}" "oci:${TEMPDIR}/container/"

echo "Custom kickstart detected, will use..."
cp "${KICKSTART}" "${TEMPDIR}/local.ks"

echo "Pack iso to ${OUTPUT_ISO}"
cd "${TEMPDIR}"
sudo mkksiso --ks local.ks --add ${TEMPDIR}/container/ \
     --cmdline "console=tty0 console=ttyS0,115200n8" \
     --rm-args "quiet" \
    "${BOOT_ISO}" "${OUTPUT_ISO}"
rm -rf "${TEMPDIR}"
echo Done
