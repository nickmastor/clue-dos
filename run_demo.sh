#!/bin/bash
#
# run_demo.sh -- play a full bot-only game and capture a transcript.
#
#   Usage:  ./run_demo.sh [num_players] [seed]
#   Example: ./run_demo.sh 3 42
#
# Starts the moderator plus N scripted bots, all talking over the real UNIX
# socket, and writes each process's output to ./transcript/.  The moderator log
# is the authoritative game transcript; each bot log shows that player's view
# (its private cards and its reasoning).
#
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

N=${1:-3}
SEED=${2:-42}
NAMES=(Alice Bob Carol Dave Erin Frank Grace Heidi)

OUT="$HERE/transcript"
rm -rf "$OUT" /tmp/cluedo
mkdir -p "$OUT"

echo "Starting moderator (players=$N, seed=$SEED)..."
python3 -u moderator.py --players "$N" --seed "$SEED" >"$OUT/moderator.log" 2>&1 &
MOD=$!

# give the socket a moment to appear
for _ in $(seq 1 50); do [ -S /tmp/cluedo/cluedo.sock ] && break; sleep 0.1; done

BOTS=()
for i in $(seq 1 "$N"); do
    name=${NAMES[$((i-1))]:-player$i}
    python3 -u bot.py --name "$name" --delay 0.05 --seed "$((SEED+i))" \
        >"$OUT/bot_${name}.log" 2>&1 &
    BOTS+=($!)
    sleep 0.2
done

echo "Playing... (moderator pid $MOD)"
wait "$MOD" 2>/dev/null || true
kill "${BOTS[@]}" 2>/dev/null || true

echo
echo "=================== GAME TRANSCRIPT (moderator) ==================="
cat "$OUT/moderator.log"
echo "=================================================================="
echo
echo "Full logs written to: $OUT/"
echo "  moderator.log        -- authoritative game log (use this for screenshots)"
for i in $(seq 1 "$N"); do
    name=${NAMES[$((i-1))]:-player$i}
    echo "  bot_${name}.log -- ${name}'s private view & reasoning"
done
