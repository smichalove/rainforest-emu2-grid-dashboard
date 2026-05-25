#!/usr/bin/env bash

# This script configures a Raspberry Pi to ensure the HDMI port is always hot (force hotplug),
# making it boot into the correct display output even when no display is connected at boot.

set -euo pipefail

# Ensure the script is run with root privileges
if [ "$EUID" -ne 0 ]; then
  echo "ERROR: Please run this script with sudo:"
  echo "  sudo bash $0"
  exit 1
fi

echo "=== Configuring HDMI Force Hotplug on Raspberry Pi ==="

# 1. Locate config.txt and cmdline.txt
CONFIG_PATH=""
CMDLINE_PATH=""

if [ -f "/boot/firmware/config.txt" ]; then
  CONFIG_PATH="/boot/firmware/config.txt"
  CMDLINE_PATH="/boot/firmware/cmdline.txt"
elif [ -f "/boot/config.txt" ]; then
  CONFIG_PATH="/boot/config.txt"
  CMDLINE_PATH="/boot/cmdline.txt"
else
  echo "ERROR: Could not locate config.txt in /boot or /boot/firmware."
  exit 1
fi

echo "Found config file: ${CONFIG_PATH}"
echo "Found cmdline file: ${CMDLINE_PATH}"

# 2. Configure legacy/firmware hotplug in config.txt
echo "Updating ${CONFIG_PATH}..."
if grep -q "^#\?hdmi_force_hotplug=" "${CONFIG_PATH}"; then
  # Replace existing line (commented or uncommented)
  sed -i 's/^#\?hdmi_force_hotplug=.*/hdmi_force_hotplug=1/' "${CONFIG_PATH}"
else
  # Append to end of file
  echo "hdmi_force_hotplug=1" >> "${CONFIG_PATH}"
fi
echo "✓ Set hdmi_force_hotplug=1 in config.txt"

# 3. Configure KMS (Kernel Mode Setting) hotplug in cmdline.txt
# Modern Raspberry Pi OS (using vc4-kms-v3d) requires vc4.force_hotplug in cmdline.txt
if grep -q "vc4-kms-v3d" "${CONFIG_PATH}" || grep -q "vc4-fkms-v3d" "${CONFIG_PATH}"; then
  echo "Updating ${CMDLINE_PATH} for KMS driver..."
  if ! grep -q "vc4.force_hotplug" "${CMDLINE_PATH}"; then
    # Append vc4.force_hotplug=3 to force hotplug on both HDMI-0 and HDMI-1
    # We must keep everything on a single line in cmdline.txt
    sed -i 's/$/ vc4.force_hotplug=3/' "${CMDLINE_PATH}"
    echo "✓ Appended vc4.force_hotplug=3 to cmdline.txt"
  else
    echo "✓ vc4.force_hotplug is already configured in cmdline.txt"
  fi
else
  echo "KMS driver not active; relying on config.txt settings."
fi

echo "=== HDMI Configuration Complete ==="

# 4. Disable Wi-Fi Power Management (prevents Pi from dropping offline)
echo "=== Configuring Wi-Fi Power Save to OFF ==="
if command -v nmcli &> /dev/null; then
  echo "Using NetworkManager to disable Wi-Fi power save..."
  # Find active wlan connection name and disable powersave
  WLAN_CONN=$(nmcli -t -f DEVICE,CONNECTION device | awk -F: '$1=="wlan0"{print $2}')
  if [ -n "$WLAN_CONN" ]; then
    nmcli connection modify "$WLAN_CONN" 802-11-wireless.powersave 2
    echo "✓ Wi-Fi power save disabled in NetworkManager for connection: $WLAN_CONN"
  else
    echo "wlan0 interface not found or inactive in NetworkManager. Skipping."
  fi
else
  echo "NetworkManager not found. Creating a systemd service to disable Wi-Fi power save..."
  SERVICE_FILE="/etc/systemd/system/wifi_powersave@.service"
  cat << 'EOF' > "$SERVICE_FILE"
[Unit]
Description=Set WiFi power save %i
After=sys-subsystem-net-devices-wlan0.device

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/sbin/iw dev wlan0 set power_save %i

[Install]
WantedBy=sys-subsystem-net-devices-wlan0.device
EOF
  systemctl daemon-reload
  systemctl enable wifi_powersave@off.service
  echo "✓ Enabled wifi_powersave@off systemd service."
fi

# Try to immediately turn off power save for the current session
if command -v iw &> /dev/null; then
  iw dev wlan0 set power_save off || true
  echo "✓ Disabled power_save for the current session."
fi

echo "=== Pi Setup Complete ==="
echo "Please reboot your Raspberry Pi for all changes to take effect:"
echo "  sudo reboot"
