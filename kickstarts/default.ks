# Bootstrap NUC Kickstart
# Two identical ~1TB drives — discovered dynamically, no hardcoded sda/sdb
# Layout: rootvg on drive 1, microshift-storage on drive 2

text --non-interactive

# Deploy the bootc container image (embedded in the ISO by mkksiso)
ostreecontainer --url=/run/install/repo/container --transport=oci --no-signature-verification

network --bootproto=dhcp --device=eno1 --activate --onboot=on

rootpw --plaintext redhat123

reboot

# ---------------------------------------------------------------
# %pre: Discover target drives by size to avoid sda/sdb naming
# instability. With identical drives, device names can swap
# between boots. Sorted by by-id (serial) for deterministic
# drive selection.
# ---------------------------------------------------------------
%pre --interpreter=/bin/bash --log=/tmp/ks-pre.log
#!/bin/bash

declare -a CANDIDATES

for dev in /sys/block/sd*; do
    name=$(basename "$dev")
    removable=$(cat "$dev/removable" 2>/dev/null || echo 1)
    size_bytes=$(blockdev --getsize64 "/dev/$name" 2>/dev/null || echo 0)
    size_gb=$((size_bytes / 1073741824))

    # Target: non-removable drives > 500G (our ~931G drives)
    # Excludes USB installer (~119G) and other small media
    if [ "$removable" = "0" ] && [ "$size_gb" -gt 500 ]; then
        CANDIDATES+=("$name")
    fi
done

# Sort by by-id (serial number) for deterministic ordering across boots
declare -a SORTED
for id_link in $(ls /dev/disk/by-id/ 2>/dev/null | grep -v '\-part' | sort); do
    target=$(basename "$(readlink -f "/dev/disk/by-id/$id_link")")
    for c in "${CANDIDATES[@]}"; do
        if [ "$target" = "$c" ]; then
            already=false
            for s in "${SORTED[@]}"; do [ "$s" = "$c" ] && already=true; done
            $already || SORTED+=("$c")
        fi
    done
done

# Fallback: alphabetical if by-id resolution didn't produce results
if [ ${#SORTED[@]} -lt 2 ]; then
    IFS=$'\n' SORTED=($(printf '%s\n' "${CANDIDATES[@]}" | sort -u))
fi

DISK1="${SORTED[0]}"
DISK2="${SORTED[1]}"

echo "DISK1=$DISK1" > /tmp/discovered-disks
echo "DISK2=$DISK2" >> /tmp/discovered-disks
echo "Discovered: DISK1=$DISK1 DISK2=$DISK2 (from ${#CANDIDATES[@]} candidates)" >> /tmp/ks-pre.log

cat > /tmp/part-include <<KEOF
# Disk setup — scoped to discovered drives only
ignoredisk --only-use=${DISK1},${DISK2}
zerombr
clearpart --all --initlabel --disklabel=gpt --drives=${DISK1},${DISK2}
bootloader --boot-drive=${DISK1}
# --- Drive 1 (by serial): OS ---
part /boot/efi --fstype=efi  --size=600  --ondisk=${DISK1}
part /boot     --fstype=xfs  --size=1024 --ondisk=${DISK1}
part pv.01     --grow --size=1 --ondisk=${DISK1}
# --- Drive 2 (by serial): Microshift storage ---
part pv.02     --grow --size=1 --ondisk=${DISK2}
KEOF
%end

%include /tmp/part-include

# OS root volume group (drive 1)
volgroup rootvg pv.01
logvol swap --vgname=rootvg --fstype=swap --name=swaplv --size=8192
logvol /    --vgname=rootvg --fstype=xfs  --name=rootlv --grow --size=1

# Microshift TopoLVM storage (drive 2, used by Harbor PVCs, etc.)
volgroup microshift-storage pv.02
