"""Game logic for Clue-dOS: cards, board graph, dealing, movement. No I/O."""

import heapq
import random

PERSONS = [
    "Captain Mustard",
    "Doctor Orchid",
    "Professor Plum",
    "Miss Scarlett",
    "Colonel Green",
    "Mrs Peacock",
]

WEAPONS = [
    "Pistol",
    "Pen",
    "Rope",
    "Wrench",
    "Candlestick",
    "Dagger",
]

# Clockwise perimeter order, so consecutive rooms are drawn adjacent on the map.
ROOMS = [
    "Kitchen",
    "Ballroom",
    "Conservatory",
    "Billiard Room",
    "Library",
    "Study",
    "Hall",
    "Lounge",
    "Dining Room",
]

POLICE_STATION = "Police Station"   # centre of the board; accuse from here only
LOCATIONS = ROOMS + [POLICE_STATION]


def build_deck():
    return PERSONS + WEAPONS + ROOMS


# Board graph: rooms in a ring (2 steps apart), each linked to the centre (3).
_RING_COST = 2
_SPOKE_COST = 3


def _build_graph():
    graph = {loc: {} for loc in LOCATIONS}
    n = len(ROOMS)
    for i, room in enumerate(ROOMS):
        nxt = ROOMS[(i + 1) % n]
        graph[room][nxt] = _RING_COST
        graph[nxt][room] = _RING_COST
        graph[room][POLICE_STATION] = _SPOKE_COST
        graph[POLICE_STATION][room] = _SPOKE_COST
    return graph


_GRAPH = _build_graph()


def _distances_from(start):
    dist = {loc: float("inf") for loc in LOCATIONS}
    dist[start] = 0
    pq = [(0, start)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u]:
            continue
        for v, w in _GRAPH[u].items():
            nd = d + w
            if nd < dist[v]:
                dist[v] = nd
                heapq.heappush(pq, (nd, v))
    return dist


def reachable(current, roll):
    """Locations (excluding `current`) within `roll` steps, sorted."""
    dist = _distances_from(current)
    return sorted(loc for loc in LOCATIONS if loc != current and dist[loc] <= roll)


def deal(num_players, seed=None):
    """Return (solution, hands, weapon_room). Solution is one card per category;
    the rest are dealt out; the 6 weapons go into 6 of the 9 rooms."""
    if num_players < 2:
        raise ValueError("need at least 2 players")

    rng = random.Random(seed)
    solution = {
        "person": rng.choice(PERSONS),
        "weapon": rng.choice(WEAPONS),
        "room": rng.choice(ROOMS),
    }

    sealed = set(solution.values())
    rest = [c for c in build_deck() if c not in sealed]
    rng.shuffle(rest)
    hands = [[] for _ in range(num_players)]
    for i, card in enumerate(rest):
        hands[i % num_players].append(card)
    for h in hands:
        h.sort()

    rooms_shuffled = ROOMS[:]
    rng.shuffle(rooms_shuffled)
    weapon_room = {w: rooms_shuffled[i] for i, w in enumerate(WEAPONS)}
    return solution, hands, weapon_room


_CELL_W = 13


def _tokens_at(location, player_locs, out_players):
    return [name + ("*" if name in out_players else "")
            for name, loc in player_locs.items() if loc == location]


def _fit(s, w):
    return s if len(s) <= w else s[: w - 1] + "."


class _Canvas:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.g = [[" "] * w for _ in range(h)]

    def put(self, x, y, s):
        if 0 <= y < self.h:
            for i, ch in enumerate(s):
                if 0 <= x + i < self.w:
                    self.g[y][x + i] = ch

    def box(self, x, y, room, room_weapons, player_locs, out_players):
        W = _CELL_W
        toks = _tokens_at(room, player_locs, out_players)
        self.put(x, y, "+" + "-" * W + "+")
        self.put(x, y + 1, "|" + room.center(W) + "|")
        self.put(x, y + 2, "|" + _fit(" w: " + (", ".join(room_weapons.get(room, [])) or "-"), W).ljust(W) + "|")
        self.put(x, y + 3, "|" + _fit(" " + (", ".join(toks) if toks else ""), W).ljust(W) + "|")
        self.put(x, y + 4, "+" + "-" * W + "+")

    def __str__(self):
        return "\n".join("".join(r).rstrip() for r in self.g)


_BOX_W = _CELL_W + 2
_XL, _XC, _XR = 0, 21, 42
_POS = {
    "Kitchen":       (_XL, 0),
    "Ballroom":      (_XC, 0),
    "Conservatory":  (_XR, 0),
    "Billiard Room": (_XR, 8),
    "Library":       (_XR, 16),
    "Study":         (_XR, 24),
    "Hall":          (_XC, 24),
    "Lounge":        (_XL, 24),
    "Dining Room":   (_XL, 8),
}


def format_board(room_weapons, player_locs, out_players=()):
    """ASCII map: rooms around the edge, corridors labelled with step cost,
    Police Station in the centre, with weapons and player tokens drawn in."""
    out_players = set(out_players)
    c = _Canvas(58, 31)

    for room, (x, y) in _POS.items():
        c.box(x, y, room, room_weapons, player_locs, out_players)

    c.put(_XL + _BOX_W, 1, "--2--")
    c.put(_XC + _BOX_W, 1, "--2--")
    c.put(_XR + 7, 5, "|"); c.put(_XR + 7, 6, "2"); c.put(_XR + 7, 7, "|")
    c.put(_XR + 7, 13, "|"); c.put(_XR + 7, 14, "2"); c.put(_XR + 7, 15, "|")
    c.put(_XR + 7, 21, "|"); c.put(_XR + 7, 22, "2"); c.put(_XR + 7, 23, "|")
    c.put(_XC + _BOX_W, 25, "--2--")
    c.put(_XL + _BOX_W, 25, "--2--")
    c.put(_XL + 7, 5, "|"); c.put(_XL + 7, 6, "2"); c.put(_XL + 7, 7, "|")
    for yy in range(13, 24):
        c.put(_XL + 7, yy, "|")
    c.put(_XL + 7, 18, "2")

    toks = _tokens_at(POLICE_STATION, player_locs, out_players)
    px, py, pw = 19, 12, 17
    c.put(px, py, "+" + "=" * pw + "+")
    c.put(px, py + 1, "|" + "POLICE".center(pw) + "|")
    c.put(px, py + 2, "|" + "STATION".center(pw) + "|")
    c.put(px, py + 3, "|" + "accuse here".center(pw) + "|")
    c.put(px, py + 4, "|" + _fit((", ".join(toks) if toks else "-"), pw).center(pw) + "|")
    c.put(px, py + 5, "+" + "=" * pw + "+")

    title = "THE MANSION  (corridor number = steps; middle is 3 from any room)"
    out_line = "\n(* = out of the game, still reveals cards)" if out_players else ""
    return title + "\n\n" + str(c) + out_line


def card_category(card):
    if card in PERSONS:
        return "person"
    if card in WEAPONS:
        return "weapon"
    if card in ROOMS:
        return "room"
    return None


if __name__ == "__main__":
    sol, hands, wr = deal(3, seed=1)
    print("Solution:", sol)
    for i, h in enumerate(hands):
        print("Player", i, "hand:", h)
    print("Weapons:", wr)
    print("From Library on a 3:", reachable("Library", 3))
