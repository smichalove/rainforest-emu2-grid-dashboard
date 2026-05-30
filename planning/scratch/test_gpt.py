import sys

device = "/dev/rdisk4"

try:
    with open(device, "rb") as f:
        # Read the sector 2 (LBA 2) where the Partition Entry Array starts
        # sector size is usually 512 bytes, LBA 2 starts at 1024 bytes
        f.seek(1024)
        entry1 = f.read(128)
        
        # Start sector is at offset 32 (8 bytes)
        start_sector = int.from_bytes(entry1[32:40], "little")
        print(f"Partition 1 start sector: {start_sector}")
        
        # Partition name is at offset 56 (72 bytes) in UTF-16LE
        name_bytes = entry1[56:128]
        # decode UTF-16LE, stripping trailing nulls
        name = name_bytes.decode("utf-16-le").rstrip("\x00")
        print(f"Partition 1 name: '{name}'")
except Exception as e:
    print(f"Error: {e}")
