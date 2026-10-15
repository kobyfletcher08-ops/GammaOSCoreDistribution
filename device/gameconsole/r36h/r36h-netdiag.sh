#!/system/bin/sh
# SPDX-License-Identifier: Apache-2.0
# Read-only by default. Uses Android's tools and the bundled BusyBox.
set -eu
action=${1:-report}
iface=${2:-}
case "$action" in
  report)
    printf '%s\n' '=== USB devices ==='
    for device in /sys/bus/usb/devices/*; do
      [ -f "$device/idVendor" ] || continue
      printf '%s ' "${device##*/}"
      cat "$device/idVendor" "$device/idProduct"
    done
    printf '%s\n' '=== Network links and addresses ==='
    ip link
    ip -4 address
    printf '%s\n' '=== Policy routing ==='
    ip -4 rule
    ip -4 route show table all
    printf '%s\n' '=== ARP / neighbour state ==='
    ip neighbour
    printf '%s\n' '=== Ethernet service ==='
    dumpsys ethernet || true
    printf '%s\n' '=== Connectivity service ==='
    dumpsys connectivity || true
    printf '%s\n' '=== Root and bundled tools ==='
    command -v su || true
    command -v busybox || true
    command -v pppd || true
    ;;
  up)
    [ "$(id -u)" = 0 ] || { echo "Run up from an already-rooted shell." >&2; exit 1; }
    # Reject path traversal and shell syntax before using the sysfs interface.
    case "$iface" in
      ""|*[!a-zA-Z0-9_.-]*|.*) echo "Specify an Ethernet/USB interface." >&2; exit 1 ;;
    esac
    case "$iface" in
      eth*|usb*|rndis*|en*) ;;
      *) echo "Only wired Ethernet/USB interfaces are accepted." >&2; exit 1 ;;
    esac
    [ -d "/sys/class/net/$iface" ] || { echo "Interface is absent: $iface" >&2; exit 1; }
    ip link set dev "$iface" up
    echo "Link enabled. Android's Ethernet service manages DHCP, DNS and routes."
    dumpsys ethernet || true
    ;;
  *)
    echo "Usage: r36h-netdiag [report | up INTERFACE]" >&2
    exit 2
    ;;
esac
