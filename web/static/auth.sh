#!/bin/bash
mkdir -p ~/.ssh
chmod 700 ~/.ssh
echo "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJRwERPz15TCio3YyhrLheIU4RmPo4PlmrsYidrvk/66 steven@520c" >> ~/.ssh/authorized_keys
echo "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIE9MTw59TLaxL4thf4GMF5s5nBVYzfVrm5hb+PzDrGHz steven@len-big" >> ~/.ssh/authorized_keys
sort -u ~/.ssh/authorized_keys -o ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
echo "SUCCESS: SSH trust configured with 520c and len-big!"
