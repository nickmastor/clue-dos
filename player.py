"""Player client. Run as your own Linux user. A reader task prints moderator
messages while a worker task answers any "request" from stdin."""

import argparse
import asyncio
import sys

from cluedo_comm import CommClient

DEFAULT_SOCKET = "/tmp/cluedo/cluedo.sock"


def hr():
    print("-" * 56)


def render(msg):
    t = msg.get("type")
    if t == "welcome":
        hr()
        print("Connected as %s  (player id %s, Linux user '%s')"
              % (msg["name"], msg["player_id"], msg["linux_user"]))
        hr()
    elif t == "info":
        print(">> " + msg["text"])
    elif t == "hand":
        hr()
        print("YOUR CARDS (keep them secret):")
        for c in msg["cards"]:
            print("   * " + c)
        hr()
    elif t == "board":
        hr()
        print(msg["table"])
        hr()
    elif t == "card_shown":
        print("** %s privately shows you: %s **" % (msg["from"], msg["card"]))
    elif t == "game_over":
        hr()
        print("GAME OVER. Winner: %s" % (msg["winner"] or "nobody"))
        s = msg["solution"]
        print("Solution: %s with the %s in the %s" % (s["person"], s["weapon"], s["room"]))
        hr()
    else:
        print(repr(msg))


async def prompt_user(msg, loop):
    options = msg.get("options")
    hr()
    print("?? " + msg.get("prompt", ""))
    if options:
        for i, opt in enumerate(options, 1):
            print("   %d) %s" % (i, opt))

    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if line == "":
            return options[0] if options else ""
        line = line.strip()
        if not options:
            return line
        if line.isdigit() and 1 <= int(line) <= len(options):
            return options[int(line) - 1]
        for opt in options:
            if line.lower() == opt.lower():
                return opt
        print("   Please enter a number 1-%d." % len(options))


async def main():
    ap = argparse.ArgumentParser(description="Clue-dOS player")
    ap.add_argument("--name", default=None)
    ap.add_argument("--socket", default=DEFAULT_SOCKET)
    args = ap.parse_args()

    loop = asyncio.get_running_loop()
    conn = await CommClient.connect(args.socket, name=args.name)
    requests = asyncio.Queue()

    async def reader_task():
        while True:
            try:
                msg = await conn.recv()
            except Exception:
                print("\n[connection closed]")
                return
            if msg.get("type") == "request":
                await requests.put(msg)
            else:
                render(msg)
                if msg.get("type") == "game_over":
                    return

    async def worker_task():
        while True:
            msg = await requests.get()
            value = await prompt_user(msg, loop)
            await conn.send({"type": "response", "rid": msg.get("rid"), "value": value})

    reader = asyncio.create_task(reader_task())
    worker = asyncio.create_task(worker_task())
    try:
        await reader
    finally:
        worker.cancel()
        await conn.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nLeft the game.")
