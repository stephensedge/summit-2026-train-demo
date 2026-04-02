#!/bin/bash

echo "Forcing re-deploy of manifests..."
oc apply -k /etc/microshift/manifests.d/dhcp/
oc apply -k /etc/microshift/manifests.d/dns/
oc apply -k /etc/microshift/manifests.d/network-install/
oc apply -k /etc/microshift/manifests.d/oc-mirror/
oc apply -k /etc/microshift/manifests.d/registry/
oc apply -k /etc/microshift/manifests.d/registry-init/
