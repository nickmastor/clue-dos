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
| `setup_users.sh` | Creates the `player1..N` Linux users. |

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

## How to play

On your turn: press **ENTER** to roll, type the **number** of where to move. In
a room you make a suggestion (pick a suspect, then a weapon); players holding
any named card reveal one to you privately. At the Police Station you may make
your one accusation: right wins, wrong puts you out (but you keep revealing
cards). Deduce the three sealed cards from what you're shown and what no one can
disprove.
