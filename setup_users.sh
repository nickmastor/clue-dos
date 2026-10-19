#!/bin/bash
#
# setup_users.sh -- create the Linux users for Clue-Linux and install the game
# into a world-readable shared folder so every player can run it.
#
# Each player must be a SEPARATE Linux user (assignment requirement).
#
#   Usage:   sudo ./setup_users.sh <num_players>
#   Example: sudo ./setup_users.sh 3
#   Clean:   sudo ./setup_users.sh clean <num_players>
#
# Creates users player1..playerN, fixes their home directories, and copies all
# the game source into /opt/clue-dos (readable by everyone).  You then run the
# moderator as yourself and start each player with `sudo -u playerN ...`
# (no group membership, no re-login, no password juggling needed).
#
set -e

HERE="$(cd "$(dirname "$0")" && pwd)"
SHARE=/opt/clue-dos

if [ "$(id -u)" -ne 0 ]; then
    echo "Please run with sudo." >&2
    exit 1
fi

# ---- teardown ----
if [ "$1" = "clean" ]; then
    N=${2:-8}
    for i in $(seq 1 "$N"); do
        userdel -r "player$i" 2>/dev/null || true
    done
    groupdel cluedo 2>/dev/null || true
    rm -rf "$SHARE" /tmp/cluedo
    echo "Removed player1..player$N, group cluedo, and $SHARE."
    exit 0
fi

N=${1:-3}

groupadd -f cluedo

# Install the game where any user can read and run it.
mkdir -p "$SHARE"
cp "$HERE"/*.py "$SHARE"/
chmod 755 "$SHARE"
chmod 644 "$SHARE"/*.py
echo "Installed game to $SHARE"

for i in $(seq 1 "$N"); do
    U="player$i"
    if ! id "$U" >/dev/null 2>&1; then
        useradd -m -s /bin/bash "$U"
        echo "created $U"
    else
        echo "$U already exists"
    fi
    # Make sure the home dir exists and is owned by the player, so a login
    # shell (su - / sudo -iu) works cleanly.
    mkdir -p "/home/$U"
    chown "$U:$U" "/home/$U"
    chmod 755 "/home/$U"
    usermod -aG cluedo "$U" 2>/dev/null || true
    # A simple password (only needed if you use `su`; `sudo -u` does not need it).
    echo "$U:play$i" | chpasswd 2>/dev/null || true
done

cat <<EOF

================================================================
Setup complete for player1..player$N.

START THE MODERATOR (as yourself -- no sudo, no --group):

    cd $SHARE
    python3 moderator.py --players $N --allow-prefix player

THEN open $N terminals, one player each (no password needed):

EOF
NAMES=(Alice Bob Carol Dave Erin Frank Grace Heidi)
for i in $(seq 1 "$N"); do
    name=${NAMES[$((i-1))]:-player$i}
    echo "    sudo -u player$i python3 $SHARE/player.py --name $name"
done
cat <<EOF

The moderator prints the real Linux user it verified for each player.
Teardown later with:  sudo ./setup_users.sh clean $N
================================================================
EOF
