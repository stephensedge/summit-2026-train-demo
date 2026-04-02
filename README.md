# summit-2026-train-demo
This repo contains the automation, code, etc, to set up the train demo from RH Summit 2026.

## Architecture
TODO

## Requirements
- ~300GB of space, available to be handed out by LVM
- at least 8GB of RAM is recommended
- Two network interfaces - one as the "external" interface, and one for the "internal" network

## Required Inputs
The following items are required:
rhel-9.6-boot-x86_64.iso - Download this from the [customer portal](https://access.cdn.redhat.com/content/origin/files/sha256/36/36a06d4c36605550c2626d5af9ee84fc2badce9e71010b7e94a9a469a0335d63/rhel-9.6-x86_64-boot.iso?user=c4a941d10d1dfd979fe3d43a671bd992&_auth_=1775179399_b650c042f24408bfffacf11033e35194).

Mount the iso and grab the following file:
```
EFI/BOOT/grubx64.efi
```

Put it in: `./images/execution-environment/`

From your local Linux system, grab your shim file from:
```
/boot/efi/EFI/fedora/grubx64.efi
```

Put it in: `./images/execution-environment/`

Copy the following into a file (such as build-args.txt) with the appropriate values:
```
# Note - do not single-quote anything in this file, even if there are specical characters
# Quoting anything will break the deployment
RHSM_ORG=your-org-number
RHSM_AK=your-activation-key
PULL_SECRET=your-pull-secret
SSH_KEY=your-ssh-key
EXTERNAL_INTERFACE=enp3s0
INTERNAL_INTERFACE=eno1
RHEL_BOOT_ISO=~/Downloads/rhel-9.6-x86_64-boot.iso
KICKSTART=~/path/to/kickstart.ks
BASE_DNS_ZONE=whatever.com
REGISTRY_ADMIN_PASSWORD=password
BOOTSTRAP_USER_PASSWORD=password

# OCP 4.20.14 has been tested, however anything "stable" should work
OPENSHIFT_VERSION=4.20.14
ACP_API_IP=192.168.100.10
ACP_INGRESS_IP=192.168.100.11
ACP_DNS_SERVER=192.168.100.1
ACP_ROUTER_ADDRESS=192.168.100.1

NODE0_IP_ADDRESS=192.168.100.20
NODE0_CLUSTER_INTERFACE=enp3s0
NODE0_CLUSTER_INTERFACE_MAC_ADDRESS=00:00:01:04:0c:da
NODE0_INSTALL_DEVICE=eui.00000000000000000026b768710aab15
NODE0_STORAGE_INTERFACE=enp2s0
NODE0_STORAGE_IP_ADDRESS=192.168.108.20

NODE1_IP_ADDRESS=192.168.100.21
NODE1_CLUSTER_INTERFACE=enp3s0
NODE1_CLUSTER_INTERFACE_MAC_ADDRESS=00:00:01:04:18:fa
NODE1_INSTALL_DEVICE=eui.00000000000000000026b768710aaeb5
NODE1_STORAGE_INTERFACE=enp2s0
NODE1_STORAGE_IP_ADDRESS=192.168.108.21

NODES_STORAGE_DEVICE=/dev/disk/by-path/pci-0000:01:00.0-nvme-1

ARBITER_IP_ADDRESS=192.168.100.22
ARBITER_CLUSTER_INTERFACE=enp1s0
ARBITER_CLUSTER_INTERFACE_MAC_ADDRESS=00:00:01:03:09:89
ARBITER_INSTALL_DEVICE=eui.00000000000000000026b7686f39b445
ARBITER_STORAGE_INTERFACE=enp2s0
ARBITER_STORAGE_IP_ADDRESS=192.168.108.22
```

Create two files to house the password for `ansible`, the user created in the bootstrap image, and a vnc password:
```
ansible-user.txt
vnc-password.txt
```

In the ansible-user.txt file, format it accordingly:
```
ansible:THEPASSWORDYOUWANT
```

In the vnc-password.txt file, simply enter the desired password:
```
YOURPASSWORDHERE
```

## Building
The provided makefile will build the required images and create an installation ISO - simply run `make` to kick off the process.

The makefile contains some variables at the top:
```
EXPORT_DIR               ?= ./images/bootstrap/overlay/usr/lib/container-images
BUILD_ARG_FILE           ?= ./ignore/build-args.txt
BUILD_USER_FILE          ?= ./ignore/ansible-user.txt
VNC_PASSWORD_FILE        ?= ./ignore/vnc-password.txt

KICKSTART	             ?= ./kickstarts/default.ks
RHEL_BOOT_ISO            ?= ./rhel-9.6-x86_64-boot.iso
BOOTSTRAP_ISO_OUTPUT_DIR ?= /tmp/install-bootstrap.iso
```

These can be overriden on the command line if needed:
```
make KICKSTART=./kickstarts/advantech.ks RHEL_BOOT_ISO=~/Downloads/rhel-9.6-x86_64-boot.iso
```

To cleanup what's been built, simply run:
```
make clean
```
