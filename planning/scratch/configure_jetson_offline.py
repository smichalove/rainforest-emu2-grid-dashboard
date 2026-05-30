import os
import shutil

ROOT = "/Volumes/Untitled"

def configure():
    print("--- 1. Appending user 'nvidia' to passwd/shadow/group/gshadow ---")
    
    # passwd
    passwd_path = os.path.join(ROOT, "etc/passwd")
    with open(passwd_path, "r") as f:
        passwd_content = f.read()
    if "nvidia" not in passwd_content:
        with open(passwd_path, "a") as f:
            f.write("nvidia:x:1000:1000:nvidia,,,:/home/nvidia:/bin/bash\n")
        print("Added nvidia to passwd")
    else:
        print("nvidia already in passwd")

    # shadow
    shadow_path = os.path.join(ROOT, "etc/shadow")
    with open(shadow_path, "r") as f:
        shadow_content = f.read()
    if "nvidia" not in shadow_content:
        # password is 'nvidia' (openssl passwd -6 nvidia)
        with open(shadow_path, "a") as f:
            f.write("nvidia:$6$5gl5SChG4cfupp3e$d9PSQnk.XRIo8Sr6VOwVZhxRKbRYqqmRWS8qRXVN/NGgV1Ybv8pRdPB2DM1kxg8VFTpymetz2eR45K./T0yxQ.:19949:0:99999:7:::\n")
        print("Added nvidia to shadow")
    else:
        print("nvidia already in shadow")

    # group & gshadow additions
    groups_to_add = ["adm", "dialout", "sudo", "audio", "video", "plugdev"]
    
    # group
    group_path = os.path.join(ROOT, "etc/group")
    with open(group_path, "r") as f:
        group_lines = f.readlines()
    
    new_group_lines = []
    nvidia_group_exists = False
    for line in group_lines:
        parts = line.strip().split(":")
        if len(parts) >= 3:
            group_name = parts[0]
            if group_name == "nvidia":
                nvidia_group_exists = True
            if group_name in groups_to_add:
                # Add nvidia to this group
                if len(parts) == 4 and parts[3]:
                    users = parts[3].split(",")
                    if "nvidia" not in users:
                        users.append("nvidia")
                    parts[3] = ",".join(users)
                else:
                    if len(parts) < 4:
                        parts.append("nvidia")
                    else:
                        parts[3] = "nvidia"
            line = ":".join(parts) + "\n"
        new_group_lines.append(line)
        
    if not nvidia_group_exists:
        new_group_lines.append("nvidia:x:1000:\n")
        print("Added nvidia group to group")
        
    with open(group_path, "w") as f:
        f.writelines(new_group_lines)
    print("Updated group file memberships")

    # gshadow
    gshadow_path = os.path.join(ROOT, "etc/gshadow")
    with open(gshadow_path, "r") as f:
        gshadow_lines = f.readlines()
        
    new_gshadow_lines = []
    nvidia_gshadow_exists = False
    for line in gshadow_lines:
        parts = line.strip().split(":")
        if len(parts) >= 3:
            group_name = parts[0]
            if group_name == "nvidia":
                nvidia_gshadow_exists = True
            if group_name in groups_to_add:
                # Add nvidia to users in gshadow (parts[3] is the users list)
                if len(parts) == 4 and parts[3]:
                    users = parts[3].split(",")
                    if "nvidia" not in users:
                        users.append("nvidia")
                    parts[3] = ",".join(users)
                else:
                    if len(parts) < 4:
                        parts.append("nvidia")
                    else:
                        parts[3] = "nvidia"
            line = ":".join(parts) + "\n"
        new_gshadow_lines.append(line)
        
    if not nvidia_gshadow_exists:
        new_gshadow_lines.append("nvidia:*::\n")
        print("Added nvidia group to gshadow")
        
    with open(gshadow_path, "w") as f:
        f.writelines(new_gshadow_lines)
    print("Updated gshadow file memberships")

    print("\n--- 2. Setting up home directory and permissions ---")
    home_dir = os.path.join(ROOT, "home/nvidia")
    skel_dir = os.path.join(ROOT, "etc/skel")
    
    if not os.path.exists(home_dir):
        os.makedirs(home_dir)
        print(f"Created home directory: {home_dir}")
        # copy skel files
        for item in os.listdir(skel_dir):
            s = os.path.join(skel_dir, item)
            d = os.path.join(home_dir, item)
            if os.path.isdir(s):
                shutil.copytree(s, d, symlinks=True)
            else:
                shutil.copy2(s, d)
        print("Copied skeleton files")
    else:
        print("Home directory already exists")

    # Fix ownership of home directory to 1000:1000
    # On macOS, we can use os.chown(path, 1000, 1000) but it might require root
    print("Setting permissions...")
    for root_dir, dirs, files in os.walk(home_dir):
        try:
            os.chown(root_dir, 1000, 1000)
        except PermissionError:
            pass
        for mom in dirs:
            try:
                os.chown(os.path.join(root_dir, mom), 1000, 1000)
            except PermissionError:
                pass
        for mom in files:
            try:
                os.chown(os.path.join(root_dir, mom), 1000, 1000)
            except PermissionError:
                pass
    print("Attempted to fix ownership of home directory (any failures were ignored, we will fix on Jetson)")

    print("\n--- 3. Bypassing oem-config target by pointing default.target to multi-user.target ---")
    default_target_path = os.path.join(ROOT, "etc/systemd/system/default.target")
    if os.path.islink(default_target_path) or os.path.exists(default_target_path):
        os.remove(default_target_path)
    os.symlink("/lib/systemd/system/multi-user.target", default_target_path)
    print(f"Set {default_target_path} -> /lib/systemd/system/multi-user.target")

    print("\n--- 4. Appending systemd.unit=multi-user.target to extlinux.conf ---")
    extlinux_path = os.path.join(ROOT, "boot/extlinux/extlinux.conf")
    with open(extlinux_path, "r") as f:
        conf_lines = f.readlines()
        
    new_conf_lines = []
    for line in conf_lines:
        if line.strip().startswith("APPEND ") and "systemd.unit=multi-user.target" not in line:
            line = line.strip() + " systemd.unit=multi-user.target\n"
            print("Appended systemd.unit=multi-user.target to APPEND line")
        new_conf_lines.append(line)
        
    with open(extlinux_path, "w") as f:
        f.writelines(new_conf_lines)
    print("Updated extlinux.conf")
    print("\nConfiguration offline patch completed successfully!")

if __name__ == "__main__":
    configure()
