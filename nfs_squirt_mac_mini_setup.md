# NFS Storage & "Squirt" Telemetry Pipeline Setup Guide (Mac Mini)

This runbook contains complete, self-executing instructions for Antigravity (AGY) to configure high-speed NFS data transfers across the local 2.5 Gbps cluster backplane between Linux host nodes (`520c` / `len-big`) and the Apple Silicon M4 Mac Mini (`Stevens-Mini-2`).

---

## 1. Cluster Identity & Network Parameters

| Role / Identifier | Value | Notes |
| :--- | :--- | :--- |
| **Mac Mini Hostname** | `Stevens-Mini-2` | macOS Sequoia (Darwin arm64) |
| **Mac Mini IP** | `192.168.8.103` | Pinned static DHCP lease on 2.5 Gbps (`en8`) |
| **Mac Mini User** | `stevenmichalove` | UID: `501`, GID: `20` (staff) |
| **Primary Linux Server** | `520c` (`192.168.8.181`) | Ubuntu Linux (2.5 Gbps `enp2s0`), user `steven` |
| **Secondary Linux Server** | `len-big` (`192.168.8.51`) | Ubuntu Linux (2.5 Gbps), user `steven` |
| **Local LAN Subnet** | `192.168.8.0/24` | Netmask `255.255.255.0` |

---

## Architecture A: Mac Mini as NFS Server (Push / Squirt Directly to Mac Mini)

> **Use Case**: Linux nodes (or data feeder scripts) write data directly to the Mac Mini's local SSD over NFS.

### Step A.1: Configure Mac Mini (`Stevens-Mini-2` @ `192.168.8.103`)

Run as `stevenmichalove`:

```bash
# 1. Create the target destination directory
mkdir -p /Users/stevenmichalove/squirt_data
chmod 775 /Users/stevenmichalove/squirt_data

# 2. Append export entry to /etc/exports (idempotent check)
EXPORT_LINE="/Users/stevenmichalove/squirt_data -mapall=stevenmichalove -network 192.168.8.0 -mask 255.255.255.0"
if ! grep -q "/Users/stevenmichalove/squirt_data" /etc/exports 2>/dev/null; then
    echo "$EXPORT_LINE" | sudo tee -a /etc/exports
fi

# 3. Check syntax and restart nfsd daemon
sudo nfsd checkexports
sudo nfsd enable
sudo nfsd restart

# 4. Verify local export visibility
showmount -e localhost
```

> [!IMPORTANT]
> **macOS Security Gatekeeper Requirement (Full Disk Access):**
> On macOS Sonoma & Sequoia, `/sbin/nfsd` requires **Full Disk Access** to serve files:
> - If `showmount` works remotely but client write requests fail with `Permission denied` or `Operation not permitted`:
>   1. Open **System Settings -> Privacy & Security -> Full Disk Access**.
>   2. Click **+**, press `Cmd + Shift + G`, paste `/sbin/nfsd`, and click Open.
>   3. Toggle `nfsd` to **ON**.

---

### Step A.2: Mount & Write from Linux Client (e.g. `520c` @ `192.168.8.181`)

Run on the Linux client node:

```bash
# 1. Install NFS client package
sudo apt-get update && sudo apt-get install -y nfs-common

# 2. Verify visibility of Mac Mini's export
showmount -e 192.168.8.103

# 3. Create persistent mount target
sudo mkdir -p /mnt/macmini_squirt
sudo chown -R $USER:$USER /mnt/macmini_squirt

# 4. Test mount
sudo mount -t nfs 192.168.8.103:/Users/stevenmichalove/squirt_data /mnt/macmini_squirt

# 5. Verify write capability
touch /mnt/macmini_squirt/test_ping.txt && rm /mnt/macmini_squirt/test_ping.txt
echo "NFS Write to Mac Mini OK"

# 6. Configure persistent automount in /etc/fstab (Optional)
if ! grep -q "macmini_squirt" /etc/fstab; then
    echo "192.168.8.103:/Users/stevenmichalove/squirt_data /mnt/macmini_squirt nfs defaults,_netdev,rw,timeo=14,intr 0 0" | sudo tee -a /etc/fstab
fi
```

---

## Architecture B: Mac Mini as NFS Client (Pull from Central Linux Storage)

> **Use Case**: `520c` hosts the shared data pool (`/home/steven/squirt_pool`), and the Mac Mini mounts it to read/process data locally.

### Step B.1: Configure Linux Server (`520c` @ `192.168.8.181`)

Run on `520c`:

```bash
# 1. Ensure NFS kernel server is installed and running
sudo apt-get update && sudo apt-get install -y nfs-kernel-server

# 2. Create the storage pool directory
sudo mkdir -p /home/steven/squirt_pool
sudo chown -R steven:steven /home/steven/squirt_pool
sudo chmod -R 775 /home/steven/squirt_pool

# 3. Add export entry to /etc/exports
# NOTE: 'insecure' is MANDATORY for macOS clients to connect from unprivileged ports
EXPORT_CONFIG="/home/steven/squirt_pool 192.168.8.0/24(rw,sync,no_subtree_check,all_squash,anonuid=1000,anongid=1000,insecure)"
if ! grep -q "/home/steven/squirt_pool" /etc/exports; then
    echo "$EXPORT_CONFIG" | sudo tee -a /etc/exports
fi

# 4. Re-export and restart service
sudo exportfs -rav
sudo systemctl restart nfs-kernel-server
sudo systemctl status nfs-kernel-server --no-pager
```

---

### Step B.2: Mount on Mac Mini (`Stevens-Mini-2` @ `192.168.8.103`)

Run on `Stevens-Mini-2`:

```bash
# 1. Verify remote export from 520c
showmount -e 192.168.8.181

# 2. Create local mount directory in user home
mkdir -p /Users/stevenmichalove/mnt/squirt_pool

# 3. Mount with macOS-optimized flags (resvport, bg, intr)
sudo mount -t nfs -o resvport,rw,bg,intr,noatime 192.168.8.181:/home/steven/squirt_pool /Users/stevenmichalove/mnt/squirt_pool

# 4. Verify mount and test read/write
df -h /Users/stevenmichalove/mnt/squirt_pool
touch /Users/stevenmichalove/mnt/squirt_pool/test_write.tmp && rm /Users/stevenmichalove/mnt/squirt_pool/test_write.tmp
echo "Mount and write to 520c successful!"
```

---

## 3. High-Speed "Squirt" Benchmark Test (2.5 Gbps Verification)

Antigravity can test the raw write throughput over the 2.5 GbE backplane with `dd`:

```bash
# Write 1GB test file over NFS to measure wire speed
dd if=/dev/zero of=/mnt/macmini_squirt/test_1gb.bin bs=1M count=1000 status=progress
rm /mnt/macmini_squirt/test_1gb.bin
```
*Expected 2.5 GbE throughput: ~220–280 MB/s.*

---

## 4. Troubleshooting Quick Reference

| Issue | Root Cause | Immediate Fix |
| :--- | :--- | :--- |
| `RPC: Program not registered` | Server NFS daemon stopped | Linux: `sudo systemctl restart nfs-kernel-server`<br>macOS: `sudo nfsd restart` |
| `Operation not permitted` | macOS client port blocked by Linux | Add `insecure` flag to Linux `/etc/exports` or use `-o resvport` on macOS |
| `Permission denied` on macOS Server | TCC Full Disk Access blocking `/sbin/nfsd` | Enable `/sbin/nfsd` under macOS **System Settings -> Privacy & Security -> Full Disk Access** |
| `Mount point is not responding` | Stale connection or IP change | Force unmount on client: `sudo umount -f /mount/path` |
