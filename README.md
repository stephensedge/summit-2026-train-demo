# Bootstrap Build - Edge Lab

Forked from [RedHatEdge/summit-2026-train-demo](https://github.com/RedHatEdge/summit-2026-train-demo). Customized for home lab deployment with 10.26.100.0/24 internal cluster network.

> **Note:** The IPs, MACs, device paths, and credentials shown throughout this README reflect my specific lab environment. Substitute your own values where needed.

## Architecture

- **Bootstrap NUC** - RHEL 9.6 bootc + Microshift 4.20 running DNS, DHCP, TFTP, Harbor registry, oc-mirror
- **NODE0 / NODE1** - OCP 4.20 masters (MS-01 hardware, NVMe drives)
- **ARBITER** - OCP 4.20 arbiter for etcd quorum (Intel NUC, SATA drives)

### Network Layout

| Network | Subnet | Purpose |
|---------|--------|---------|
| External (eno1) | 192.168.100.0/24 (DHCP) | Home LAN, admin access |
| Internal (enp0s20f0u2) | 10.26.100.0/24 | Cluster network, PXE, DNS, DHCP |
| Storage (VLAN 18) | 10.26.108.0/24 | Portworx storage (10GbE MikroTik) |

## Prerequisites

### On your build machine (laptop)

- `podman`, `skopeo`, `mkksiso` installed
- Logged into `registry.redhat.io`: `podman login registry.redhat.io`
- RHEL 9.6 boot ISO at `./rhel-9.6-x86_64-boot.iso`
- EFI files at `./images/execution-environment/`:
  - `shimx64.efi` (from `/boot/efi/EFI/redhat/shimx64.efi` on a RHEL 9 system)
  - `grubx64.efi` (from `/boot/efi/EFI/redhat/grubx64.efi` on a RHEL 9 system)

### Configuration files in `./ignore/`

These are gitignored (contain secrets). Create them before building:

**`build-args.txt`** - See the example in this README below.

**`ansible-user.txt`**:
```
ansible:YOUR_PASSWORD
```

**`vnc-password.txt`**:
```
YOUR_VNC_PASSWORD
```

### SSH Key

Generate a key pair you'll use to access the nodes:
```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_bootstrap -N "" -C "yourname@lab"
```

Put the PUBLIC key in `build-args.txt` as `SSH_KEY=`.

## Building

### 1. Build the ISO

```bash
cd /path/to/bootstrap-build
make create-bootstrap-install-iso
```

This chains the full pipeline: builds all component images (DNS, DHCP, TFTP, oc-mirror, execution-environment), exports them, builds the bootstrap bootc image, and creates the installer ISO.

Output: `install-bootstrap.iso` (~7 GB)

### 2. Write to USB

```bash
# Identify your USB drive
lsblk

# Write
sudo dd if=install-bootstrap.iso of=/dev/sdX bs=4M status=progress oflag=direct
sync
```

### 3. Clean up build artifacts

```bash
make clean
sudo rm -f install-bootstrap.iso
podman system prune -af
```

## Deploying the Bootstrap NUC

### 1. Install

- Boot the NUC from the USB drive
- Anaconda runs the kickstart automatically
- NUC reboots into the bootstrap system

### 2. First boot setup

```bash
ssh -i ~/.ssh/id_bootstrap root@192.168.100.156

export KUBECONFIG=/var/lib/microshift/resources/kubeadmin/kubeconfig
echo 'export KUBECONFIG=/var/lib/microshift/resources/kubeadmin/kubeconfig' >> ~/.bashrc
```

### 3. Copy SSH key for node access

From your laptop:
```bash
scp ~/.ssh/id_bootstrap root@192.168.100.156:/root/.ssh/id_bootstrap
ssh -i ~/.ssh/id_bootstrap root@192.168.100.156 'chmod 600 /root/.ssh/id_bootstrap'
```

### 4. Wait for all services

```bash
# Watch pods come up
watch oc get pods -A
```

Wait for these to be Running/Completed:
- `lvms-operator` + `vg-manager` (storage)
- All `harbor-*` pods (registry)
- `oc-mirror` shows **Completed** (mirrors OCP images to Harbor, takes ~10 min)

### 5. Start network-install

After oc-mirror completes:
```bash
oc delete pod -n network-install --all
sleep 180 && oc get pods -n network-install
```

All three should show Running:
- `generate-install-media-0` (generates PXE boot files)
- `pubsrv` (serves rootfs + kubeconfig over HTTP)
- `tftp-0` (serves PXE boot files)

## Installing OCP on the Nodes

### 1. PXE boot all three nodes

- Plug NODE0, NODE1, and ARBITER into the internal network
- Set BIOS to network/PXE boot
- Power on all three simultaneously

The GRUB menu auto-selects "Deploy OCP Cluster" after 60 seconds.

### 2. Monitor the install

From the bootstrap NUC:

```bash
# Watch for DHCP leases (confirms PXE boot)
oc logs -n dhcp dhcp-0 | grep DHCPACK | awk '{print $3, $4}' | sort -u

# Watch for static IPs (confirms NMState applied)
watch -n10 'ping -c1 -W1 10.26.100.20 2>&1 | tail -1; ping -c1 -W1 10.26.100.21 2>&1 | tail -1; ping -c1 -W1 10.26.100.22 2>&1 | tail -1'

# SSH into the rendezvous node (NODE0) to watch agent progress
ssh -i /root/.ssh/id_bootstrap -o StrictHostKeyChecking=no core@10.26.100.20 'sudo journalctl TAG=agent -f'

# Check API VIP
ping -c1 -W1 10.26.100.10 && echo "API VIP up" || echo "API VIP not yet"
```

### 3. Access the OCP cluster

Once the API VIP (10.26.100.10) is up:
```bash
curl -s http://pubsrv-network-install.apps.bootstrap.summit2026.com/kubeconfig -o /root/acp-kubeconfig
export KUBECONFIG=/root/acp-kubeconfig
oc get nodes
oc get clusterversion
```

The kubeadmin password:
```bash
curl -s http://pubsrv-network-install.apps.bootstrap.summit2026.com/kubeadmin-password
```

## Pulling upstream updates

```bash
git fetch upstream
git merge upstream/main
# Resolve any conflicts (keep 10.26.100.x IPs, console=tty0, etc.)
```

## rootDeviceHints

OCP 4.20's `openshift-install` is picky about `rootDeviceHints`:

| Field | Accepts | Does NOT accept |
|-------|---------|-----------------|
| `deviceName` | `/dev/sda`, `/dev/disk/by-path/pci-*` | `/dev/disk/by-id/*` |
| `wwn` | Raw WWN for SATA (`0x5002538e...`) | NVMe EUI values, full paths |

This lab uses:
- **NODE0/NODE1 (NVMe):** `deviceName: /dev/disk/by-path/pci-0000:01:00.0-nvme-1`
- **ARBITER (SATA):** `deviceName: /dev/sda`

To find your by-path values, boot a node from a live ISO and run:
```bash
lsblk -o NAME,SIZE,PATH
ls /dev/disk/by-path/ | grep nvme
```

## build-args.txt

```
RHSM_ORG=12868589
RHSM_AK=ak-rhsm
PULL_SECRET={"auths":{...your-pull-secret...}}
SSH_KEY=ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIG34z9vorjTwd8cPo0OU3mhC37pr7LVZHFdsBfz91vM9 stephen@lab
EXTERNAL_INTERFACE=eno1
INTERNAL_INTERFACE=enp0s20f0u2
BASE_DNS_ZONE=summit2026.com
REGISTRY_ADMIN_PASSWORD=R3dh4t123!
OPENSHIFT_VERSION=4.20.14
HOSTNAME=bootstrap

ACP_API_IP=10.26.100.10
ACP_INGRESS_IP=10.26.100.11
ACP_DNS_SERVER=10.26.100.1
ACP_ROUTER_ADDRESS=10.26.100.1

NODE0_IP_ADDRESS=10.26.100.20
NODE0_CLUSTER_INTERFACE=eno1
NODE0_CLUSTER_INTERFACE_MAC_ADDRESS=e8:ff:1e:d3:ed:03
NODE0_INSTALL_DEVICE=/dev/disk/by-path/pci-0000:01:00.0-nvme-1
NODE0_STORAGE_INTERFACE=enp6s0f4u2c2
NODE0_STORAGE_IP_ADDRESS=10.26.108.20

NODE1_IP_ADDRESS=10.26.100.21
NODE1_CLUSTER_INTERFACE=eno1
NODE1_CLUSTER_INTERFACE_MAC_ADDRESS=e8:ff:1e:d3:ed:23
NODE1_INSTALL_DEVICE=/dev/disk/by-path/pci-0000:01:00.0-nvme-1
NODE1_STORAGE_INTERFACE=enp5s0f4u2c2
NODE1_STORAGE_IP_ADDRESS=10.26.108.21

NODES_STORAGE_DEVICE=/dev/disk/by-id/nvme-eui.000000000000000100a07523456cf2bc

ARBITER_IP_ADDRESS=10.26.100.22
ARBITER_CLUSTER_INTERFACE=eno1
ARBITER_CLUSTER_INTERFACE_MAC_ADDRESS=94:c6:91:a3:84:6b
ARBITER_INSTALL_DEVICE=/dev/disk/by-id/wwn-0x5002538e406ca627
ARBITER_STORAGE_INTERFACE=enp0s20f0u2
ARBITER_STORAGE_IP_ADDRESS=10.26.108.22
```

### Getting stable disk IDs

Boot each node from a RHEL 9 live ISO and run:
```bash
# NVMe drives - use by-path (openshift-install requires /dev/ or /dev/disk/by-path/)
ls -la /dev/disk/by-path/ | grep nvme

# SATA drives - kernel name is fine for single-disk nodes
lsblk -o NAME,SIZE,MODEL
```

### Getting MAC addresses

```bash
ip link show eno1 | grep ether
```
