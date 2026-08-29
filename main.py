"""eucshare: tiny end-to-end-encrypted location-share relay (served by uvicorn, ONE process)."""
import asyncio, time
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState
import config
from relay import registry, ROOM_ID

app = FastAPI(title="eucshare")

@app.get("/health")
def health():
    return {"ok": True, "rooms": registry.count()}

@app.websocket("/ws/{room_id}")
async def ws_room(ws: WebSocket, room_id: str):
    if not ROOM_ID.match(room_id):
        await ws.close(code=1008); return
    await ws.accept()
    try:
        room = await registry.join(room_id, ws)
    except PermissionError:
        await ws.close(code=1013); return          # try again later / room full
    bucket, last = config.RATE_PER_S, time.monotonic()
    peers_task = asyncio.create_task(_peers_loop(ws, room))
    try:
        while True:
            text = await ws.receive_text()
            if len(text.encode("utf-8")) > config.MAX_MSG_BYTES:
                continue
            now = time.monotonic()
            bucket = min(config.RATE_PER_S, bucket + (now - last) * config.RATE_PER_S); last = now
            if bucket < 1:
                continue                            # rate limited: drop, do not disconnect
            bucket -= 1
            await registry.handle(room_id, room, ws, text)
    except WebSocketDisconnect:
        pass
    finally:
        peers_task.cancel()
        await registry.leave(room_id, ws)

async def _peers_loop(ws: WebSocket, room):
    while ws.client_state == WebSocketState.CONNECTED:
        await asyncio.sleep(config.PEERS_FRAME_S)
        try:
            await ws.send_text(registry.peers_frame(room))
        except Exception:
            return
