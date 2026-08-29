"""In-memory rooms. The relay never inspects `ct` (end-to-end encrypted by clients)."""
import asyncio, json, re, time
from typing import Dict, Optional
import config

ROOM_ID = re.compile(r"^[A-Za-z0-9_-]{22}$")

class Room:
    def __init__(self):
        self.sockets = set()
        self.latest: Dict[str, str] = {}     # sender id -> last envelope text
        self.last_seen: Dict[str, float] = {}
        self.expire_task: Optional[asyncio.Task] = None

class RoomRegistry:
    def __init__(self):
        self.rooms: Dict[str, Room] = {}

    def count(self) -> int:
        return len(self.rooms)

    async def join(self, room_id: str, ws) -> Room:
        room = self.rooms.get(room_id)
        if room is None:
            room = self.rooms[room_id] = Room()
        if room.expire_task:
            room.expire_task.cancel(); room.expire_task = None   # a reconnect cancels the TTL
        if len(room.sockets) >= config.MAX_PEERS:
            raise PermissionError("room full")
        room.sockets.add(ws)
        for text in list(room.latest.values()):                  # replay latest, once each
            await ws.send_text(text)
        return room

    async def leave(self, room_id: str, ws):
        room = self.rooms.get(room_id)
        if room is None:
            return
        room.sockets.discard(ws)
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
        sender = str(msg.get("from", ""))
        if msg.get("type") == "leave":
            room.latest.pop(sender, None); room.last_seen.pop(sender, None)
            await self._fanout(room, sender_ws, json.dumps({"type": "left", "from": sender}))
            return
        if "ct" in msg and sender:
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
