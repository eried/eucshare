"""In-memory rooms. The relay never inspects `ct` (end-to-end encrypted by clients)."""
import asyncio, json, re, time
from collections import deque
from typing import Deque, Dict, Optional
import config

ROOM_ID = re.compile(r"^[A-Za-z0-9_-]{22}$")
SENDER_ID = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
NEW_ROOM_WINDOW_S = 60.0   # sliding window behind NEW_ROOMS_PER_IP_PER_MIN
IP_SWEEP_AT = 512          # sweep stale ips out of the rate map once it holds this many

class Room:
    def __init__(self):
        self.sockets = set()
        self.latest: Dict[str, str] = {}     # sender id -> last envelope text
        self.last_seen: Dict[str, float] = {}
        self.senders: Dict[object, str] = {}  # socket -> the one sender id bound to it
        self.expire_task: Optional[asyncio.Task] = None

class RoomRegistry:
    def __init__(self):
        self.rooms: Dict[str, Room] = {}
        self.ip_sockets: Dict[str, int] = {}            # ip -> open sockets
        self.ip_new_rooms: Dict[str, Deque[float]] = {}  # ip -> recent room creations
        self.socket_ip: Dict[object, str] = {}          # socket -> ip, so leave always decrements

    def count(self) -> int:
        return len(self.rooms)

    def socket_count(self) -> int:
        return sum(len(room.sockets) for room in self.rooms.values())

    async def join(self, room_id: str, ws, ip: Optional[str] = None) -> Room:
        room = self.rooms.get(room_id)
        if ip and self.ip_sockets.get(ip, 0) >= config.MAX_CONN_PER_IP:
            raise PermissionError("too many sockets from this ip")
        if room is None:                                         # creating, not joining
            if len(self.rooms) >= config.MAX_ROOMS:
                raise PermissionError("room cap reached")
            if ip and not self._allow_new_room(ip):
                raise PermissionError("new rooms rate limited")
            room = self.rooms[room_id] = Room()
        if room.expire_task:
            room.expire_task.cancel(); room.expire_task = None   # a reconnect cancels the TTL
        if len(room.sockets) >= config.MAX_PEERS:
            raise PermissionError("room full")
        room.sockets.add(ws)
        if ip:
            self.socket_ip[ws] = ip
            self.ip_sockets[ip] = self.ip_sockets.get(ip, 0) + 1
        for text in list(room.latest.values()):                  # replay latest, once each
            try:
                await ws.send_text(text)
            except Exception:
                break                                            # dead already: leave() cleans up
        return room

    def _allow_new_room(self, ip: str) -> bool:
        now = time.monotonic()
        hits = self.ip_new_rooms.get(ip)
        if hits is None:
            hits = self.ip_new_rooms[ip] = deque()
        while hits and now - hits[0] > NEW_ROOM_WINDOW_S:
            hits.popleft()
        if len(hits) >= config.NEW_ROOMS_PER_IP_PER_MIN:
            if not hits:
                del self.ip_new_rooms[ip]                        # never keep an empty entry
            return False
        hits.append(now)
        if len(self.ip_new_rooms) > IP_SWEEP_AT:                 # keep the map from growing without bound
            for stale in [k for k, d in self.ip_new_rooms.items() if not d or now - d[-1] > NEW_ROOM_WINDOW_S]:
                del self.ip_new_rooms[stale]
        return True

    async def leave(self, room_id: str, ws):
        ip = self.socket_ip.pop(ws, None)                        # first, so every path decrements once
        if ip is not None:
            open_now = self.ip_sockets.get(ip, 0) - 1
            if open_now > 0:
                self.ip_sockets[ip] = open_now
            else:
                self.ip_sockets.pop(ip, None)
        room = self.rooms.get(room_id)
        if room is None:
            return
        room.sockets.discard(ws)
        sender = room.senders.pop(ws, None)
        if sender:                                               # tell peers at once, do not wait for staleness
            room.latest.pop(sender, None); room.last_seen.pop(sender, None)
            await self._fanout(room, ws, json.dumps({"type": "left", "from": sender}))
        if not room.sockets:
            room.expire_task = asyncio.create_task(self._expire(room_id))

    async def _expire(self, room_id: str):
        await asyncio.sleep(config.ROOM_TTL_S)
        room = self.rooms.get(room_id)
        if room is not None and not room.sockets:
            del self.rooms[room_id]

    async def handle(self, room_id: str, room: Room, sender_ws, text: str):
        try:
            msg = json.loads(text)
        except ValueError:
            return
        if not isinstance(msg, dict):
            return
        sender = msg.get("from")
        if not isinstance(sender, str) or not SENDER_ID.match(sender):
            return
        if room.senders.setdefault(sender_ws, sender) != sender:
            return                              # one sender id per socket: drop, do not disconnect
        if msg.get("type") == "leave":
            room.latest.pop(sender, None); room.last_seen.pop(sender, None)
            await self._fanout(room, sender_ws, json.dumps({"type": "left", "from": sender}))
            return
        ct = msg.get("ct")
        if isinstance(ct, str) and len(ct) <= config.MAX_CT_CHARS:
            room.latest[sender] = text
            room.last_seen[sender] = time.monotonic()
            await self._fanout(room, sender_ws, text)

    async def _fanout(self, room: Room, sender_ws, text: str):
        for other in list(room.sockets):
            if other is sender_ws:
                continue
            try:
                await other.send_text(text)
            except Exception:
                room.sockets.discard(other)

    def peers_frame(self, room: Room) -> str:
        now = time.monotonic()
        return json.dumps({"type": "peers", "seen": {k: int(now - v) for k, v in room.last_seen.items()}})

registry = RoomRegistry()
