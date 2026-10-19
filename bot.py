"""Auto-playing detective: connects like a human but answers prompts itself.
Deduces from cards it is shown and from suggestions nobody can disprove, then
accuses once each category is down to one candidate. Handy for transcripts."""

import argparse
import asyncio
import random

import game_rules as g
from cluedo_comm import CommClient

DEFAULT_SOCKET = "/tmp/cluedo/cluedo.sock"


class Bot:
    def __init__(self, name, delay):
        self.name = name
        self.delay = delay
        self.hand = set()
        self.eliminated = set()
        self.confirmed = {"person": None, "weapon": None, "room": None}
        self.room = g.POLICE_STATION
        self.last_person = None
        self.pending = None          # trio we suggested, awaiting a result
        self.shown_by_me = set()

    def candidates(self, cat):
        full = {"person": g.PERSONS, "weapon": g.WEAPONS, "room": g.ROOMS}[cat]
        if self.confirmed[cat]:
            return [self.confirmed[cat]]
        return [c for c in full if c not in self.eliminated]

    def solved(self, cat):
        return len(self.candidates(cat)) == 1

    def ready_to_accuse(self):
        return all(self.solved(c) for c in ("person", "weapon", "room"))

    def note(self, text):
        print("   [%s thinks] %s" % (self.name, text))

    def on_message(self, msg):
        t = msg.get("type")
        if t == "welcome":
            self.name = msg["name"]
        elif t == "hand":
            self.hand = set(msg["cards"])
            self.eliminated |= self.hand
            print("   [%s] my cards: %s" % (self.name, ", ".join(sorted(self.hand))))
        elif t == "card_shown":
            self.eliminated.add(msg["card"])
            self.note("was shown '%s' -> not the solution." % msg["card"])
            if self.pending and msg["card"] in self.pending:
                self.pending = None
        elif t == "info" and self.pending and "No one could disprove" in msg["text"]:
            for c in self.pending:
                if c not in self.hand:
                    self.confirmed[g.card_category(c)] = c
                    self.note("nobody could disprove '%s' and I don't hold it -> "
                              "it IS the %s!" % (c, g.card_category(c)))
            self.pending = None

    def decide(self, msg):
        kind, prompt = msg["kind"], msg["prompt"]
        options = msg.get("options") or []

        if kind == "roll":
            return ""

        if kind == "choice" and "move" in prompt:
            if self.ready_to_accuse() and "Police Station" in options:
                self.note("solved it. Heading to the Police Station.")
                self.room = "Police Station"
                return "Police Station"
            rooms = [o for o in options if o in g.ROOMS]
            choice = random.choice(rooms) if rooms else (options[0] if options else "stay")
            if choice in g.LOCATIONS:
                self.room = choice
            return choice

        if kind == "yesno":
            if "ACCUSATION" in prompt:
                return "yes" if self.ready_to_accuse() else "no"
            return "no" if self.ready_to_accuse() else "yes"

        if kind == "choice" and "Suspect" in prompt:
            if self.confirmed["person"]:
                return self.confirmed["person"]
            self.last_person = self._probe("person")
            return self.last_person

        if kind == "choice" and "Weapon" in prompt:
            if self.confirmed["weapon"]:
                return self.confirmed["weapon"]
            weapon = self._probe("weapon")
            self.pending = {self.last_person, weapon, self.room}
            self.note("suggesting %s with the %s in the %s"
                      % (self.last_person, weapon, self.room))
            return weapon

        if kind == "choice" and "Room" in prompt:
            return self.candidates("room")[0]

        if kind == "show":
            reuse = [c for c in options if c in self.shown_by_me]
            card = reuse[0] if reuse else options[0]
            self.shown_by_me.add(card)
            return card

        return options[0] if options else ""

    def _probe(self, cat):
        cands = self.candidates(cat)
        return random.choice([c for c in cands if c not in self.hand] or cands)


async def main():
    ap = argparse.ArgumentParser(description="Clue-dOS bot")
    ap.add_argument("--name", default=None)
    ap.add_argument("--socket", default=DEFAULT_SOCKET)
    ap.add_argument("--delay", type=float, default=0.4)
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    conn = await CommClient.connect(args.socket, name=args.name)
    bot = Bot(args.name or "bot", args.delay)
    requests = asyncio.Queue()

    async def reader_task():
        while True:
            try:
                msg = await conn.recv()
            except Exception:
                return
            bot.on_message(msg)
            if msg.get("type") == "request":
                await requests.put(msg)
            elif msg.get("type") == "info":
                print(">> " + msg["text"])
            elif msg.get("type") == "game_over":
                return

    async def worker_task():
        while True:
            msg = await requests.get()
            if args.delay:
                await asyncio.sleep(args.delay)
            await conn.send({"type": "response", "rid": msg.get("rid"),
                             "value": bot.decide(msg)})

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
        pass
