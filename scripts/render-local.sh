#!/bin/bash

# This is intended to help troubleshooting/etc by rendering out the files as they would appear in the bootc image
# Not intended for "production" use

source "$1"

rm -rf render
mkdir render
cp -r images/bootstrap/overlay/etc/microshift/manifests.d/* render/
sed -i "s/INTERNAL_INTERFACE/${INTERNAL_INTERFACE}/g" render/dhcp/manifests/configmap.yaml

# Registry/registry-init setup
sed -i "s/BASE_DNS_ZONE/${BASE_DNS_ZONE}/g" render/registry-init/manifests/configmap.yaml
sed -i "s/REGISTRY_ADMIN_PASSWORD/${REGISTRY_ADMIN_PASSWORD}/g" render/registry-init/manifests/configmap.yaml

# Network-install setup
sed -i "s/NODE0_IP_ADDRESS/${NODE0_IP_ADDRESS}/g" render/network-install/manifests/configmap.yaml
sed -i "s/NODE0_CLUSTER_INTERFACE$/${NODE0_CLUSTER_INTERFACE}/g" render/network-install/manifests/configmap.yaml
sed -i "s/NODE0_CLUSTER_INTERFACE_MAC_ADDRESS$/${NODE0_CLUSTER_INTERFACE_MAC_ADDRESS}/g" render/network-install/manifests/configmap.yaml
sed -i "s/NODE0_INSTALL_DEVICE/${NODE0_INSTALL_DEVICE}/g" render/network-install/manifests/configmap.yaml
sed -i "s/NODE0_STORAGE_INTERFACE/${NODE0_STORAGE_INTERFACE}/g" render/network-install/manifests/configmap.yaml

sed -i "s/NODE1_IP_ADDRESS/${NODE1_IP_ADDRESS}/g" render/network-install/manifests/configmap.yaml
sed -i "s/NODE1_CLUSTER_INTERFACE$/${NODE1_CLUSTER_INTERFACE}/g" render/network-install/manifests/configmap.yaml
sed -i "s/NODE1_CLUSTER_INTERFACE_MAC_ADDRESS$/${NODE1_CLUSTER_INTERFACE_MAC_ADDRESS}/g" render/network-install/manifests/configmap.yaml
sed -i "s/NODE1_INSTALL_DEVICE/${NODE1_INSTALL_DEVICE}/g" render/network-install/manifests/configmap.yaml
sed -i "s/NODE1_STORAGE_INTERFACE/${NODE1_STORAGE_INTERFACE}/g" render/network-install/manifests/configmap.yaml

sed -i "s/ARBITER_IP_ADDRESS/${ARBITER_IP_ADDRESS}/g" render/network-install/manifests/configmap.yaml
sed -i "s/ARBITER_CLUSTER_INTERFACE$/${ARBITER_CLUSTER_INTERFACE}/g" render/network-install/manifests/configmap.yaml
sed -i "s/ARBITER_CLUSTER_INTERFACE_MAC_ADDRESS$/${ARBITER_CLUSTER_INTERFACE_MAC_ADDRESS}/g" render/network-install/manifests/configmap.yaml
sed -i "s/ARBITER_INSTALL_DEVICE/${ARBITER_INSTALL_DEVICE}/g" render/network-install/manifests/configmap.yaml
sed -i "s/ARBITER_STORAGE_INTERFACE/${ARBITER_STORAGE_INTERFACE}/g" render/network-install/manifests/configmap.yaml

sed -i "s/ACP_API_IP/${ACP_API_IP}/g" render/network-install/manifests/configmap.yaml
sed -i "s/ACP_INGRESS_IP/${ACP_INGRESS_IP}/g" render/network-install/manifests/configmap.yaml
sed -i "s/PULL_SECRET/${PULL_SECRET}/g" render/network-install/manifests/configmap.yaml
sed -i "s|SSH_KEY|${SSH_KEY}|g" render/network-install/manifests/configmap.yaml
sed -i "s/ACP_DNS_SERVER/${ACP_DNS_SERVER}/g" render/network-install/manifests/configmap.yaml
sed -i "s/ACP_ROUTER_ADDRESS/${ACP_ROUTER_ADDRESS}/g" render/network-install/manifests/configmap.yaml
sed -i "s/BASE_DNS_ZONE/${BASE_DNS_ZONE}/g" render/network-install/manifests/configmap.yaml
sed -i "s/BASE_DNS_ZONE/${BASE_DNS_ZONE}/g" render/network-install/manifests/statefulset.yaml
sed -i "s/REGISTRY_ADMIN_PASSWORD/${REGISTRY_ADMIN_PASSWORD}/g" render/network-install/manifests/configmap.yaml
sed -i "s|NODES_STORAGE_DEVICE|${NODES_STORAGE_DEVICE}|g" render/network-install/manifests/configmap.yaml
sed -i "s/OPENSHIFT_VERSION/${OPENSHIFT_VERSION}/g" render/network-install/manifests/configmap.yaml

# oc-mirror setup
sed -i "s/OPENSHIFT_VERSION/${OPENSHIFT_VERSION}/g" render/oc-mirror/manifests/configmap.yaml
sed -i "s/BASE_DNS_ZONE/${BASE_DNS_ZONE}/g" render/oc-mirror/manifests/configmap.yaml
sed -i "s/REGISTRY_ADMIN_PASSWORD/${REGISTRY_ADMIN_PASSWORD}/g" render/oc-mirror/manifests/configmap.yaml
sed -i "s/BASE_DNS_ZONE/${BASE_DNS_ZONE}/g" render/oc-mirror/manifests/job.yaml
sed -i "s/PULL_SECRET/${PULL_SECRET}/g" render/oc-mirror/manifests/secret.yaml