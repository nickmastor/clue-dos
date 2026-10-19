"""Game-master process. Holds the solution, board and turn order, and drives
every player over cluedo_comm.py (one-to-one, broadcast, and concurrent reveals).
"""

import argparse
import asyncio
import itertools
import random
import shutil
import subprocess

import game_rules as g
from cluedo_comm import CommServer

DEFAULT_SOCKET = "/tmp/cluedo/cluedo.sock"

_rid = itertools.count(1)


def rid():
    return next(_rid)


_FALLBACK_FORTUNES = [
    "He who hesitates is lost... and so is the candlestick.",
    "A closed mouth gathers no foot.",
    "Trust everyone, but cut the cards.",
    "The early bird gets the worm, but the second mouse gets the cheese.",
    "You will soon be the victim of a well-planned conspiracy.",
    "Fortune favours the bold, but the butler favours the exits.",
    "Beware of all enterprises that require new weapons.",
    "The night is darkest just before the wrench.",
]


def last_words():
    """A fortune-cookie line from the `fortune` command, or a built-in fallback."""
    exe = shutil.which("fortune")
    if exe:
        try:
            out = subprocess.run([exe, "-s"], capture_output=True, text=True, timeout=3)
            text = " ".join(out.stdout.split())
            if text:
                return text
        except Exception:
            pass
    return random.choice(_FALLBACK_FORTUNES)


class Game:
    def __init__(self, server, player_ids, seed=None):
        self.srv = server
        self.ids = player_ids
        self.names = {pid: server.name(pid) for pid in player_ids}

        self.solution, hands, self.weapon_room = g.deal(len(player_ids), seed)
        self.hand = {pid: hands[i] for i, pid in enumerate(player_ids)}
        place_rng = random.Random(None if seed is None else seed * 7919 + 1)
        self.pos = {pid: place_rng.choice(g.ROOMS) for pid in player_ids}
        self.alive = {pid: True for pid in player_ids}
        self.winner = None

    async def info(self, text, exclude=()):
        print(text, flush=True)
        await self.srv.broadcast({"type": "info", "text": text}, exclude=exclude)

    async def ask(self, pid, kind, prompt, options=None, timeout=None):
        reply = await self.srv.request(
            pid, {"type": "request", "rid": rid(), "kind": kind,
                  "prompt": prompt, "options": options}, timeout=timeout)
        return None if reply is None else reply.get("value")

    async def ask_yesno(self, pid, prompt):
        return await self.ask(pid, "yesno", prompt, options=["yes", "no"]) == "yes"

    def weapons_in(self, room):
        return sorted(w for w, r in self.weapon_room.items() if r == room)

    async def opening_scene(self):
        victim = "Mr. Boddy"
        room = random.choice(g.ROOMS)
        await self.info("=" * 56)
        await self.info("          *** A MURDER AT TUDOR MANSION ***")
        await self.info("=" * 56)
        await self.info("All %d detectives have arrived. The doors lock behind you."
                        % len(self.ids))
        await self.info("%s has been found dead in the %s." % (victim, room))
        await self.info("With his final breath, %s whispered:" % victim)
        await self.info('   "%s"' % last_words())
        await self.info("One suspect, one weapon, one room, sealed in the Police "
                        "Station. Find them before the killer finds you.")
        await self.info("=" * 56)

    async def deal_and_brief(self):
        s = self.solution
        print("[moderator] solution: %s / %s / %s"
              % (s["person"], s["weapon"], s["room"]), flush=True)
        for pid in self.ids:
            await self.srv.send(pid, {"type": "hand", "cards": self.hand[pid]})
        await self.info("A murder! The sealed solution is locked in the Police Station.")
        await self.info("Detectives: " + ", ".join(self.names[p] for p in self.ids))
        await self.broadcast_board()

    async def broadcast_board(self):
        board = {room: self.weapons_in(room) for room in g.ROOMS}
        where = {self.names[p]: self.pos[p] for p in self.ids}
        out = [self.names[p] for p in self.ids if not self.alive[p]]
        table = g.format_board(board, where, out)
        print(table, flush=True)
        await self.srv.broadcast({"type": "board", "table": table})

    async def take_turn(self, pid):
        name = self.names[pid]
        await self.info("=== %s's turn ===" % name)

        await self.ask(pid, "roll", "Press ENTER to roll the dice.")
        roll = random.randint(1, 6)
        await self.info("%s rolled a %d." % (name, roll))

        choices = g.reachable(self.pos[pid], roll) + ["stay"]
        dest = await self.ask(pid, "choice",
                              "You are in %s. Where do you move?" % self.pos[pid],
                              options=choices)
        if dest and dest != "stay" and dest in g.LOCATIONS:
            self.pos[pid] = dest
        await self.info("%s is now in the %s." % (name, self.pos[pid]))
        await self.broadcast_board()

        loc = self.pos[pid]
        if loc in g.ROOMS:
            await self.srv.send(pid, {"type": "info",
                                      "text": "You are in the %s. Make your suggestion." % loc})
            person = await self.ask(pid, "choice", "Suspect?", options=g.PERSONS)
            weapon = await self.ask(pid, "choice", "Weapon?", options=g.WEAPONS)
            if person and weapon:
                await self.do_suggestion(pid, person, weapon, loc)
        elif loc == g.POLICE_STATION:
            if await self.ask_yesno(pid, "Make your final ACCUSATION? (wrong = you are out)"):
                person = await self.ask(pid, "choice", "Suspect?", options=g.PERSONS)
                weapon = await self.ask(pid, "choice", "Weapon?", options=g.WEAPONS)
                room = await self.ask(pid, "choice", "Room?", options=g.ROOMS)
                if person and weapon and room:
                    await self.do_accusation(pid, person, weapon, room)

    async def do_suggestion(self, pid, person, weapon, room):
        name = self.names[pid]
        self.weapon_room[weapon] = room   # suggested weapon moves into the room
        await self.broadcast_board()
        await self.info("%s suggests: %s with the %s in the %s."
                        % (name, person, weapon, room))

        guess = {person, weapon, room}
        # Out-of-game players still have to reveal cards.
        holders = [p for p in self.ids if p != pid and guess & set(self.hand[p])]
        if not holders:
            await self.info("No one could disprove it! A powerful clue for %s." % name)
            return

        def make_req(p):
            return {"type": "request", "rid": rid(), "kind": "show",
                    "prompt": "You hold cards matching %s's suggestion. "
                              "Choose ONE to reveal privately to %s." % (name, name),
                    "options": sorted(guess & set(self.hand[p]))}

        replies = await self.srv.gather(holders, make_req, timeout=120)
        for holder in holders:
            reply = replies.get(holder)
            matches = sorted(guess & set(self.hand[holder]))
            card = reply["value"] if reply and reply.get("value") in matches else matches[0]
            await self.srv.send(pid, {"type": "card_shown",
                                      "from": self.names[holder], "card": card})
            await self.info("%s showed a card to %s." % (self.names[holder], name),
                            exclude=(pid, holder))
            await self.srv.send(holder, {"type": "info",
                                         "text": "You revealed '%s' to %s." % (card, name)})

    async def do_accusation(self, pid, person, weapon, room):
        name = self.names[pid]
        await self.info("%s walks into the Police Station and ACCUSES: "
                        "%s with the %s in the %s!" % (name, person, weapon, room))
        if (person, weapon, room) == (self.solution["person"], self.solution["weapon"],
                                      self.solution["room"]):
            self.winner = pid
            await self.info("CORRECT! %s has solved the murder and WINS!" % name)
        else:
            self.alive[pid] = False
            await self.info("WRONG! %s is out of the game, but must still reveal "
                            "cards when asked." % name)
            await self.srv.send(pid, {"type": "info",
                                      "text": "Your accusation was wrong. You can no longer "
                                              "take turns, but you stay in to reveal cards."})

    async def play(self):
        await self.opening_scene()
        await self.deal_and_brief()
        for pid in itertools.cycle(self.ids):
            if self.winner is not None:
                break
            if not any(self.alive.values()):
                await self.info("Every detective has failed. The case goes cold.")
                break
            if not self.alive[pid]:
                continue
            await self.take_turn(pid)

        s = self.solution
        await self.srv.broadcast({
            "type": "game_over",
            "winner": self.names[self.winner] if self.winner is not None else None,
            "solution": s,
        })
        await self.info("The sealed solution was: %s with the %s in the %s."
                        % (s["person"], s["weapon"], s["room"]))


async def main():
    ap = argparse.ArgumentParser(description="Clue-dOS moderator")
    ap.add_argument("--players", type=int, default=3)
    ap.add_argument("--socket", default=DEFAULT_SOCKET)
    ap.add_argument("--group", default=None, help="shared Linux group for the socket")
    ap.add_argument("--allow-prefix", default=None,
                    help="only accept Linux users whose name starts with this")
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    server = await CommServer.start(args.socket, group=args.group,
                                    allow_prefix=args.allow_prefix)
    print("Waiting for %d players..." % args.players)
    await server.wait_players(args.players)

    ids = server.player_ids()[: args.players]
    game = Game(server, ids, seed=args.seed)
    try:
        await game.play()
    finally:
        await asyncio.sleep(0.5)
        await server.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nModerator shut down.")
