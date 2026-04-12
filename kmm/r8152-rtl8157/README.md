# r8152 RTL8157 5G Driver via KMM

The MS-01 nodes (node0/node1) have Realtek RTL8157 5G USB ethernet adapters
for the storage network. RHEL 9.6's in-tree `r8152` driver doesn't support
RTL8157 (USB ID 0BDA:8157). The kernel falls back to `cdc_ncm` and the link
runs at a degraded ~705 Mb/s Half-duplex.

This directory builds the upstream Realtek r8152 v2.20.1 driver (which has
RTL8157 support) and packages it as an OCI image deployable via the
Kernel Module Management (KMM) Operator.

## Files

- `Containerfile` - Two-stage build: DTK builder + ubi-minimal runtime
- `r8152-v2.20.1.tar.gz` - Source from github.com/wget/realtek-r8152-linux@8ee2d3108f
- `build.sh` - Patches source for RHEL 9.6, builds, and pushes to Harbor
- `module.yaml` - KMM Module CR + ServiceAccount/RBAC

## Source patch for RHEL 9.6

RHEL 9.6 reports as kernel 5.14 but backports many APIs from 5.15+, 5.17+,
5.19+, 6.4+, and 6.9+. The Realtek source uses `LINUX_VERSION_CODE` checks
that pick the wrong (old) API path. `build.sh` patches only the checks where
RHEL 9.6 genuinely has the newer API:

```sh
sed -i 's|KERNEL_VERSION(5,15,0)|KERNEL_VERSION(5,14,0)|g; \
        s|KERNEL_VERSION(5,17,0)|KERNEL_VERSION(5,14,0)|g; \
        s|KERNEL_VERSION(5,19,0)|KERNEL_VERSION(5,14,0)|g; \
        s|KERNEL_VERSION(6,4,10)|KERNEL_VERSION(5,14,0)|g; \
        s|KERNEL_VERSION(6,9,0)|KERNEL_VERSION(5,14,0)|g' r8152.c compatibility.h
```

### WARNING: Do NOT patch KERNEL_VERSION(6,1,0)

RHEL 9.6 does **NOT** have the 6.1+ NAPI changes (`netif_napi_add` 3-arg).
The 6.1.0 check correctly selects `netif_napi_add_weight` (4-arg) which
RHEL 9.6 has. Patching this caused kernel soft-lockups under sustained
Portworx replication traffic after ~30 minutes (the NAPI poll loop never
yielded, triggering the kernel watchdog). Both MS-01 nodes went
unresponsive and required hard power-cycles to recover.

An earlier attempt with v2.18.1 and a blanket sed that included 6.1.0
caused this exact failure. The fix was to use v2.20.1 with the targeted
patches above (excluding 6.1.0). This has been **stable for 12+ hours**
under production Portworx traffic.

## Cluster prereqs

1. **`Build` capability enabled** - KMM watches `build.openshift.io/v1 Build`
   at startup. Cluster install uses `baselineCapabilitySet: None` which
   excludes Build by default. Enable with:
   ```sh
   oc patch clusterversion version --type=merge -p \
     '{"spec":{"capabilities":{"additionalEnabledCapabilities":["baremetal","Console","ImageRegistry","Storage","Ingress","NodeTuning","OperatorLifecycleManager","marketplace","Build"]}}}'
   ```

2. **KMM Operator** in `openshift-kmm` namespace, channel `stable`,
   OperatorGroup with empty `targetNamespaces` (AllNamespaces mode).

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
# verify, then:
ssh core@10.26.100.21 sudo modprobe -rv cdc_mbim
oc label node node1 storage-nic-driver=r8152-rtl8157 --overwrite
```

## Verify

```sh
ssh core@<node-ip> "sudo ethtool -i storage0 | head -3; sudo ethtool storage0 | grep Speed"
# Expected: driver: r8152, version: v2.20.1, Speed: 5000Mb/s
```

## OCP upgrade

When the kernel version changes, rebuild with `./build.sh` (auto-detects
new kernel version and DTK image). KMM picks up the new tag automatically
via its `${KERNEL_FULL_VERSION}` variable in the containerImage field.
