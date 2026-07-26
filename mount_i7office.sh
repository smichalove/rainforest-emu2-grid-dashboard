#!/bin/bash
# mount_i7office.sh
# Connects to the i7office SMB shares passwordlessly using macOS Finder open command.
# Designed to run via cron to ensure the workstation shares remain mounted.

# Ensure standard system paths (including /sbin for mount) are in PATH for cron
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

SERVER_ADDRESS="i7office" # Workstation hostname i7office
IP_ADDRESS="192.168.8.82" # Fallback IP address

# Function to mount a share safely via Finder open command (passwordless via Keychain)
mount_share() {
    local share_path="$1"
    local mount_name="$2"
    
    # URL-encode spaces in the share path for matching mount output
    local encoded_share="${share_path// /%20}"
    
    # Check if this specific share is already mounted (matching the remote share path in mount output)
    if mount | grep -q "/${encoded_share} on /Volumes/"; then
        echo "✅ Share '${share_path}' is already mounted!"
    else
        echo "Attempting to mount smb://${SERVER_ADDRESS}/${share_path} via Finder..."
        # Use domain;username format to exactly match the i7office\Steven keychain entry
        open "smb://i7office;Steven@${SERVER_ADDRESS}/${share_path}"
        
        # Give macOS a moment to perform the mount
        sleep 2
        if mount | grep -q "/${encoded_share} on /Volumes/"; then
            echo "✅ Successfully mounted '${share_path}'!"
        else
            echo "❌ Mount trigger sent, check Finder for status."
        fi
    fi
}

# 1. Mount Resolve Proxy
mount_share "Resolve Proxy" "Resolve Proxy"

# 2. Mount HDrive (H: drive code root)
mount_share "HDrive" "HDrive"

# 3. Mount D (D: drive media root - Finder mounts this under /Volumes/D or /Volumes/192.168.8.82)
mount_share "D" "D"

# Check which mount point was selected by macOS for D share and suggest the symlink if /Volumes/i7office is missing
if [ ! -d "/Volumes/i7office" ]; then
    actual_mount=$(mount | grep "/D on /Volumes/" | sed -E 's/.* on (\/Volumes\/[^ ]+).*/\1/')
    
    if [ -n "$actual_mount" ] && [ "$actual_mount" != "/Volumes/i7office" ]; then
        echo
        echo "💡 [Tip] To map the default mount '$actual_mount' to your configured path '/Volumes/i7office',"
        echo "   run this command once in your terminal to create a symbolic link:"
        echo "     sudo ln -s $actual_mount /Volumes/i7office"
        echo
    fi
fi
