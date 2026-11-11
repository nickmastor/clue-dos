"""Misbehaving player used to test the Project 2/3 isolation and robustness work.

Run as one of the player Linux users, either through launch_isolated.sh (the
cgroup tests) or with `sudo -u playerN python3 attacks.py <mode>` (library tests).

    python3 attacks.py fork       # try to spawn 1000 processes   (test 1)
    python3 attacks.py mem        # allocate memory until killed  (test 2)
    python3 attacks.py cpu        # busy loops                    (test 3)
    python3 attacks.py silent     # join, then never answer       (test 4)
    python3 attacks.py quit       # join, then disconnect at once  (test 5)
    python3 attacks.py oversize   # send a length prefix of 4 GB  (test 6)
    python3 attacks.py flood      # send 100k messages, never read (test 7)
"""
import asyncio
import os
import struct
import sys
import time

SOCK = os.environ.get("CLUEDO_SOCK", "/tmp/cluedo/cluedo.sock")

# Find cluedo_comm.py whether we run from the repo or from /opt/clue-dos.
for _p in (os.path.dirname(os.path.abspath(__file__)), "/opt/clue-dos"):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from cluedo_comm import CommClient  # noqa: E402


def fork_bomb(n=1000):
    made = 0
    for _ in range(n):
        try:
            pid = os.fork()
        except OSError as e:
            print("fork refused after %d children: %s" % (made, e), flush=True)
            break
        if pid == 0:
            time.sleep(600)
            os._exit(0)
        made += 1
    print("spawned %d children" % made, flush=True)
    time.sleep(600)


def memory_hog():
    blocks = []
    while True:
        blocks.append(bytearray(10 * 1024 * 1024))   # 10 MB at a time
        print("allocated %d MB" % (len(blocks) * 10), flush=True)


def cpu_burn(n=4):
    for _ in range(n):
        if os.fork() == 0:
            while True:
                pass
    while True:
        pass


async def run(mode):
    if mode == "silent":
        c = await CommClient.connect(SOCK, name="Mallory")  # keep c referenced
        await asyncio.sleep(3600)          # join, then never read or answer
        del c
    elif mode == "quit":
        c = await CommClient.connect(SOCK, name="Mallory")
        await c.close()
    elif mode == "oversize":
        _, w = await asyncio.open_unix_connection(SOCK)
        w.write(struct.pack(">I", 4_000_000_000))   # claim a ~4 GB message
        await w.drain()
        await asyncio.sleep(3600)
    elif mode == "flood":
        c = await CommClient.connect(SOCK, name="Mallory")
        for _ in range(100_000):
            await c.send({"type": "chat", "text": "x" * 1000})
        print("flood finished", flush=True)
        await asyncio.sleep(3600)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "fork":
        fork_bomb()
    elif mode == "mem":
        memory_hog()
    elif mode == "cpu":
        cpu_burn()
    elif mode in ("silent", "quit", "oversize", "flood"):
        asyncio.run(run(mode))
    else:
        sys.exit(__doc__)
