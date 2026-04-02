#!/usr/bin/env bash
set -euo pipefail

# Retry helper
retry() {
  local -r cmd="$*"
  local -i attempt=1
  local -i max_attempts=5
  local -i delay=5

  until eval "$cmd"; do
    if (( attempt >= max_attempts )); then
      echo "Command failed after $attempt attempts: $cmd" >&2
      return 1
    fi
    echo "Attempt $attempt failed, retrying in $delay seconds..." >&2
    sleep "$delay"
    ((attempt++))
  done
}

# Function to safely bring down a connection if active
bring_down_if_up() {
  local conn="$1"
  if nmcli -t -f GENERAL.STATE con show "$conn" 2>/dev/null | grep -q "activated"; then
    echo "Bringing down active connection: $conn"
    retry "nmcli connection down \"$conn\""
  else
    echo "Connection $conn not active or not found, skipping down."
  fi
}

# Shutdown existing connections if active
bring_down_if_up "EXTERNAL_INTERFACE"
bring_down_if_up "lan"

# Modify or create connections
retry "nmcli connection modify EXTERNAL_INTERFACE connection.zone external ipv4.dns '192.168.100.1' ipv4.ignore-auto-dns no ipv4.dhcp-send-hostname no ipv6.dhcp-send-hostname no ipv4.dhcp-hostname bootstrap || true"

# Add LAN connection if it doesn't exist
if ! nmcli -t -f NAME con show | grep -qx "lan"; then
  echo "Creating new 'lan' connection..."
  retry "nmcli connection add type ethernet ifname INTERNAL_INTERFACE con-name lan ipv4.addresses 192.168.100.1/24 ipv4.dns 192.168.100.1 ipv4.dns-search summit2026.com ipv4.method manual connection.zone trusted"
  retry "nmcli connection add type vlan con-name vlan101 ifname vlan101 dev INTERNAL_INTERFACE id 101 ipv4.method manual ipv4.addresses 192.168.101.1/24"
else
  echo "'lan' connection already exists, skipping add."
fi

# Bring connections back up
retry "nmcli connection up EXTERNAL_INTERFACE"
retry "nmcli connection up lan"

echo "Network setup complete."