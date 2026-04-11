# r8152 RTL8157 5G Driver via KMM

The MS-01 nodes (node0/node1) have Realtek RTL8157 5G USB ethernet adapters
for the storage network. RHEL 9.6's in-tree `r8152` driver doesn't support
RTL8157 (USB ID 0BDA:8157). The kernel falls back to `cdc_ncm` and the link
runs at a degraded ~705 Mb/s Half-duplex.

This directory builds the upstream Realtek r8152 v2.18.1 driver (which has
RTL8157 support) and packages it as an OCI image deployable via the
Kernel Module Management (KMM) Operator.

## Files

- `Containerfile` - Two-stage build: DTK builder + ubi-minimal runtime
- `r8152-v2.18.1.tar.gz` - Source from github.com/wget/realtek-r8152-linux@a3dd2c0d8c
- `build.sh` - Builds and pushes the image to Harbor
- `module.yaml` - KMM Module CR + ServiceAccount/RBAC

## Source patch

The Realtek source uses `LINUX_VERSION_CODE` checks that don't handle
RHEL kernels well. RHEL 9.6 reports as kernel 5.14 but has many APIs from
5.15+, 5.17+, 5.19+, 6.4+, and 6.9+ backported. The version checks pick
the OLD API but the kernel actually has the NEW one. `build.sh` patches
the source by bumping every problematic threshold down to 5.14.0:

```sh
sed -i 's|KERNEL_VERSION(5,15,0)|KERNEL_VERSION(5,14,0)|g; \
        s|KERNEL_VERSION(5,17,0)|KERNEL_VERSION(5,14,0)|g; \
        s|KERNEL_VERSION(6,9,0)|KERNEL_VERSION(5,14,0)|g; \
        s|KERNEL_VERSION(5,19,0)|KERNEL_VERSION(5,14,0)|g; \
        s|KERNEL_VERSION(6,4,10)|KERNEL_VERSION(5,14,0)|g' r8152.c compatibility.h
```

## Cluster prereqs

1. **`Build` capability enabled** - KMM watches `build.openshift.io/v1 Build`
   at startup. Cluster install uses `baselineCapabilitySet: None` which
   excludes Build by default. Enable with:
   ```sh
   oc patch clusterversion version --type=merge -p \
     '{"spec":{"capabilities":{"additionalEnabledCapabilities":["baremetal","Console","ImageRegistry","Storage","Ingress","NodeTuning","OperatorLifecycleManager","marketplace","Build"]}}}'
   ```
   Wait ~3-4 minutes for openshift-controller-manager to roll out the API.

2. **KMM Operator** in `openshift-kmm` namespace, channel `stable`,
   OperatorGroup with empty `targetNamespaces` (AllNamespaces mode).
   OwnNamespace mode is unsupported and the install fails.

## Deploy

```sh
# 1. On the bootstrap NUC
cd kmm/r8152-rtl8157
./build.sh

# 2. From any kubeconfig
oc apply -f module.yaml

# 3. Roll out one node at a time
ssh core@10.26.100.20 sudo modprobe -rv cdc_mbim   # unload dependents first
oc label node node0 storage-nic-driver=r8152-rtl8157 --overwrite
# verify it worked, then:
ssh core@10.26.100.21 sudo modprobe -rv cdc_mbim
oc label node node1 storage-nic-driver=r8152-rtl8157 --overwrite
```

## Verify

```sh
ssh core@10.26.100.20 "sudo ethtool -i storage0 | head -5; sudo ethtool storage0 | grep -E 'Speed|Duplex'"
# Expected:
#   driver: r8152
#   version: v2.18.1 (2024/05/20)
#   Speed: 5000Mb/s
#   Duplex: Full
```

## OCP upgrade considerations

When the kernel version changes (OCP upgrade), KMM looks for an image
tagged with the new kernel version. The build needs to be re-run BEFORE
the upgrade rolls out, or KMM workers will fail and storage networking
will be degraded. The `build.sh` script auto-detects the running kernel
and the matching DTK image, so it just needs to be re-run after an
upgrade is staged.

## Why not the arbiter

The arbiter has a Realtek RTL8156 chip (USB ID 0BDA:8156, 2.5G max), which
the in-tree `r8152` driver supports natively. There's no benefit to running
KMM on it - and 2.5 Gbps is plenty for an arbiter that doesn't store
replicated data.
