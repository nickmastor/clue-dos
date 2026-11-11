# Clue-dOS

A text-based, multi-process murder-mystery (Werewolves/Clue style) for 3-6
players. A sealed solution (one suspect, one weapon, one room) is hidden; the
rest of the 21 cards are dealt out. Each player is a separate Linux user and
process; you move around a nine-room mansion, make suggestions to pull clues
out of the other players, and race to accuse correctly.

No installation or compiling needed, just **Python 3.8+ on Linux**.

## Files

| File | What it is |
| --- | --- |
| **`cluedo_comm.py`** | **The communications library** (single file). UNIX stream sockets + asyncio. |
| `moderator.py` | Game server. Run once; it deals cards and runs the game. |
| `player.py` | A player client. Run once per player, each as a different Linux user. |
| `game_rules.py` | Cards, board, dealing, movement (no networking). |
| `bot.py` | An auto-player, used by `run_demo.sh`. |
| `run_demo.sh` | Plays a full bot-only game (one command). |
| `setup_users.sh` | Creates the `player1..N` Linux users, installs to `/opt/clue-dos`. |
| `launch_isolated.sh` | Starts a player inside a systemd cgroup with resource limits (Project 2/3). |
| `attacks.py` | Misbehaving-player tool used to test the isolation and robustness fixes. |

## Communications library

**Name/location:** `./cluedo_comm.py`. Primitive: **UNIX-domain stream sockets
with async I/O (asyncio)**; messages are length-prefixed JSON.

```
# server (moderator)
server = await CommServer.start(path, group=None, allow_prefix=None)
await server.wait_players(n)
await server.send(pid, msg)              # one-to-one
await server.multicast(ids, msg)         # a group
await server.broadcast(msg, exclude=())  # everyone
await server.recv(pid, timeout=None)
await server.request(pid, msg, timeout)  # send, then await a reply
await server.gather(ids, msg, timeout)   # send to many at once, collect replies
await server.close()

# client (player)
conn = await CommClient.connect(path, name)
await conn.send(msg); msg = await conn.recv(); await conn.close()
```

## Run it

**Quick demo (bots play themselves):**
```bash
./run_demo.sh 3
```

**Real game, one Linux user per player:**
```bash
sudo ./setup_users.sh 3                                   # make player1..3
cd /opt/clue-dos
python3 moderator.py --players 3 --allow-prefix player    # in your terminal
```
Then one terminal per player:
```bash
sudo -u player1 python3 /opt/clue-dos/player.py --name Alice
sudo -u player2 python3 /opt/clue-dos/player.py --name Bob
sudo -u player3 python3 /opt/clue-dos/player.py --name Carol
```
The game starts when the last player connects. Clean up later with
`sudo ./setup_users.sh clean 3`.

## Isolation and robustness (Project 2/3)

The improvement for Project 2/3 is an **isolation mechanism plus robustness
fixes** so that one misbehaving player can no longer stall or exhaust the
moderator.

**cgroup isolation (per player).** Instead of a plain `sudo -u`, launch each
player inside a systemd transient cgroup with CPU, memory, and task limits:
```bash
sudo ./launch_isolated.sh 1 Alice      # MemoryMax=128M TasksMax=20 CPUQuota=20%
# override: MEM=64M TASKS=10 CPU=10% sudo ./launch_isolated.sh 1 Alice
```
Confirm the limits applied (second terminal):
```bash
systemctl show cluedo-p1 -p MemoryMax -p TasksMax -p CPUQuotaPerSecUSec
systemd-cgtop -n 1
```
A fork bomb, memory hog, or CPU burn inside a player's own process is then
capped to that player's cgroup and cannot take down the VM or the game.

**Library/moderator robustness.** The library now caps message size
(`MAX_MSG`), bounds each player's inbox (`INBOX_MAX`, backpressure), and wakes a
waiting `recv` when a player disconnects. The moderator gives every request a
timeout (`--ask-timeout`, default 30 s), matches replies to requests by `rid`,
and drops players who disconnect. Net effect: a silent player, a disconnect, an
oversized length prefix, or a message flood no longer hangs or bloats the game.

**Testing.** `attacks.py` drives each case:
```bash
# library/robustness tests (run as a player user, or your own user for a local test)
python3 attacks.py silent     # join then never answer  -> turn is skipped
python3 attacks.py quit       # join then disconnect     -> player dropped
python3 attacks.py oversize   # 4 GB length prefix        -> rejected, memory flat
python3 attacks.py flood      # 100k messages             -> bounded inbox, memory flat
# cgroup tests (run the attacker through the launcher, on the VM)
sudo ./launch_isolated.sh 1 Mallory   # then inside: run attacks.py fork / mem / cpu
```
Use `--ask-timeout 2` on the moderator to see the timeouts quickly.

## How to play

On your turn: press **ENTER** to roll, type the **number** of where to move. In
a room you make a suggestion (pick a suspect, then a weapon); players holding
any named card reveal one to you privately. At the Police Station you may make
your one accusation: right wins, wrong puts you out (but you keep revealing
cards). Deduce the three sealed cards from what you're shown and what no one can
disprove.
