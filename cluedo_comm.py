"""Communications library: UNIX stream sockets + asyncio, length-prefixed JSON.

Server:  CommServer.start / wait_players / send / multicast / broadcast /
         recv / request / gather / close
Client:  CommClient.connect / send / recv / close
Messages are JSON dicts with a "type" key.
"""

import asyncio
import json
import os
import pwd
import socket
import struct

_LEN = struct.Struct(">I")
MAX_MSG = 64 * 1024   # largest message body we accept from a client (P3)
INBOX_MAX = 100       # messages buffered per player before we stop reading (P4)


class MessageTooLarge(ValueError):
    """A length prefix claimed more than MAX_MSG bytes."""


async def send_msg(writer, obj):
    data = json.dumps(obj).encode("utf-8")
    writer.write(_LEN.pack(len(data)) + data)
    await writer.drain()


async def recv_msg(reader):
    header = await reader.readexactly(_LEN.size)
    (length,) = _LEN.unpack(header)
    if length > MAX_MSG:
        # Check BEFORE readexactly, so we never allocate the claimed size (P3).
        raise MessageTooLarge("message of %d bytes exceeds MAX_MSG" % length)
    body = await reader.readexactly(length)
    return json.loads(body.decode("utf-8"))


def _clean_name(raw):
    """Keep client names printable and short so one player can't garble the
    board or flood the table with a giant pasted username."""
    if not raw:
        return ""
    s = "".join(ch for ch in str(raw) if ch.isprintable() and ch not in "\t")
    return s.strip()[:16]


def peer_credentials(sock):
    """(pid, uid, gid) of the peer, as reported by the kernel via SO_PEERCRED."""
    creds = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED,
                            struct.calcsize("3i"))
    return struct.unpack("3i", creds)


class _PlayerConn:
    def __init__(self, pid, name, linux_user, reader, writer):
        self.pid = pid
        self.name = name
        self.linux_user = linux_user
        self.reader = reader
        self.writer = writer
        self.inbox = asyncio.Queue(maxsize=INBOX_MAX)   # bounded: backpressure (P4)
        self.connected = True


class CommServer:
    def __init__(self):
        self._players = {}
        self._next_id = 0
        self._server = None
        self._path = None
        self._join_event = asyncio.Event()
        self._allow_prefix = None

    @classmethod
    async def start(cls, path, group=None, allow_prefix=None):
        self = cls()
        self._path = path
        self._allow_prefix = allow_prefix

        dirpath = os.path.dirname(path)
        os.makedirs(dirpath, exist_ok=True)
        if os.path.exists(path):
            os.unlink(path)

        self._server = await asyncio.start_unix_server(self._handle, path=path)

        # Restrict the socket to a shared group if we can; otherwise fall back
        # to world-accessible (the SO_PEERCRED check is the real gate anyway).
        applied_group = False
        if group:
            try:
                import grp
                gid = grp.getgrnam(group).gr_gid
                os.chown(path, -1, gid)
                os.chmod(path, 0o660)
                os.chown(dirpath, -1, gid)
                os.chmod(dirpath, 0o770)
                applied_group = True
            except Exception as e:
                print("[comm] group %r unavailable (%s); socket left open." % (group, e))
        if not applied_group:
            try:
                os.chmod(dirpath, 0o777)
            except Exception:
                pass
            os.chmod(path, 0o777)

        print("[comm] listening on", path)
        return self

    async def _handle(self, reader, writer):
        sock = writer.get_extra_info("socket")
        try:
            _, uid, _ = peer_credentials(sock)
            linux_user = pwd.getpwuid(uid).pw_name
        except Exception:
            linux_user = "unknown"

        if self._allow_prefix and not linux_user.startswith(self._allow_prefix):
            try:
                await send_msg(writer, {"type": "info",
                                        "text": "Rejected: user %r not allowed." % linux_user})
            finally:
                writer.close()
            print("[comm] rejected", linux_user)
            return

        try:
            hello = await recv_msg(reader)
        except Exception:
            writer.close()
            return
        name = _clean_name(hello.get("name")) or linux_user

        pid = self._next_id
        self._next_id += 1
        conn = _PlayerConn(pid, name, linux_user, reader, writer)
        self._players[pid] = conn

        # Everything after registration runs under one try/finally so that a
        # drop at ANY point (even during the welcome send) is handled cleanly
        # instead of throwing an unhandled exception (P2).
        try:
            await send_msg(writer, {"type": "welcome", "player_id": pid,
                                    "name": name, "linux_user": linux_user})
            print("[comm] %d joined: %s (%s)" % (pid, name, linux_user))
            self._join_event.set()
            while True:
                msg = await recv_msg(reader)
                await conn.inbox.put(msg)   # waits while the inbox is full: backpressure (P4)
        except (asyncio.IncompleteReadError, ConnectionError, OSError, ValueError):
            pass   # EOF, reset, oversized (MessageTooLarge), or bad JSON: treat as a disconnect
        finally:
            conn.connected = False
            try:
                writer.close()
            except Exception:
                pass
            # Wake any recv() waiting on this player (P2). If the inbox is full,
            # drop the oldest message to make room for the wake-up sentinel.
            if conn.inbox.full():
                conn.inbox.get_nowait()
            conn.inbox.put_nowait(None)
            print("[comm] %d (%s) left" % (pid, name))

    def player_ids(self):
        return sorted(self._players.keys())

    def name(self, pid):
        return self._players[pid].name

    def linux_user(self, pid):
        return self._players[pid].linux_user

    async def wait_players(self, n):
        while len(self._players) < n:
            self._join_event.clear()
            await self._join_event.wait()

    async def send(self, pid, msg):
        conn = self._players.get(pid)
        if conn and conn.connected:
            try:
                await send_msg(conn.writer, msg)
            except Exception:
                conn.connected = False

    async def multicast(self, ids, msg):
        await asyncio.gather(*(self.send(pid, msg) for pid in ids))

    async def broadcast(self, msg, exclude=()):
        await self.multicast([p for p in self._players if p not in exclude], msg)

    def is_connected(self, pid):
        conn = self._players.get(pid)
        return bool(conn and conn.connected)

    async def recv(self, pid, timeout=None):
        """Next message from pid. Returns None on timeout, or once pid has
        disconnected (a sentinel None is queued on disconnect, see _handle)."""
        conn = self._players.get(pid)
        if conn is None or (not conn.connected and conn.inbox.empty()):
            return None
        try:
            return await (conn.inbox.get() if timeout is None
                          else asyncio.wait_for(conn.inbox.get(), timeout))
        except asyncio.TimeoutError:
            return None

    async def request(self, pid, msg, timeout=None):
        await self.send(pid, msg)
        return await self.recv(pid, timeout)

    async def gather(self, ids, msg, timeout=None):
        """Send to many players at once and collect replies, {pid: reply|None}."""
        async def one(pid):
            payload = msg(pid) if callable(msg) else msg
            try:
                await self.send(pid, payload)
                return pid, await self.recv(pid, timeout)
            except Exception:
                return pid, None
        return dict(await asyncio.gather(*(one(p) for p in ids)))

    async def close(self):
        # Drop connections first: Python 3.12's wait_closed() blocks on them.
        for conn in list(self._players.values()):
            try:
                conn.writer.close()
            except Exception:
                pass
        if self._server:
            self._server.close()
            try:
                await asyncio.wait_for(self._server.wait_closed(), timeout=2)
            except Exception:
                pass
        if self._path and os.path.exists(self._path):
            try:
                os.unlink(self._path)
            except OSError:
                pass


class CommClient:
    def __init__(self, reader, writer):
        self._reader = reader
        self._writer = writer

    @classmethod
    async def connect(cls, path, name=None):
        reader, writer = await asyncio.open_unix_connection(path=path)
        self = cls(reader, writer)
        await self.send({"type": "join", "name": name})
        return self

    async def send(self, msg):
        await send_msg(self._writer, msg)

    async def recv(self):
        return await recv_msg(self._reader)

    async def close(self):
        self._writer.close()
        try:
            await self._writer.wait_closed()
        except Exception:
            pass
