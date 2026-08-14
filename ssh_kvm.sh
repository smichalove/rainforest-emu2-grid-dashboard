#!/usr/bin/expect -f
# Automatically SSH into the ONE KVM at 192.168.8.204
set timeout 10
spawn ssh -o StrictHostKeyChecking=no root@192.168.8.204
expect "password:"
send "Tr1llE0036k\r"
interact
