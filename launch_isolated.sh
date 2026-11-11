#!/bin/bash
# launch_isolated.sh -- start one player as its own Linux user, inside a
# systemd cgroup with resource limits (Project 2/3 isolation mechanism, P5).
#
#   Usage:   sudo ./launch_isolated.sh <player-number> <name>
#   Example: sudo ./launch_isolated.sh 1 Alice
#
# Override the limits with environment variables:
#   MEM=128M SWAP=0 TASKS=20 CPU=20% sudo ./launch_isolated.sh 1 Alice
#
# Confirm the limits applied (from a second terminal):
#   systemctl show cluedo-p1 -p MemoryMax -p TasksMax -p CPUQuotaPerSecUSec
#   systemd-cgtop -n 1
set -e

if [ "$(id -u)" -ne 0 ]; then
    echo "Run with sudo." >&2
    exit 1
fi
if [ -z "$1" ]; then
    echo "usage: sudo $0 <player-number> <name>" >&2
    exit 1
fi

N="$1"
NAME="${2:-player$N}"
MEM="${MEM:-128M}"
SWAP="${SWAP:-0}"      # MemorySwapMax: 0 means a memory hog is killed at MEM, not swapped
TASKS="${TASKS:-20}"
CPU="${CPU:-20%}"

# --pty keeps the player's terminal input working (the ENTER-to-roll prompt).
# --uid=playerN keeps SO_PEERCRED happy (the moderator still sees the real user).
exec systemd-run --pty --wait --collect \
    --unit="cluedo-p$N" --uid="player$N" \
    -p MemoryMax="$MEM" -p MemorySwapMax="$SWAP" -p TasksMax="$TASKS" -p CPUQuota="$CPU" \
    python3 /opt/clue-dos/player.py --name "$NAME"
