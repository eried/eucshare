"""eucshare: tiny end-to-end-encrypted location-share relay (served by uvicorn, ONE process)."""
import asyncio, time
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState
import config
from relay import registry, ROOM_ID

app = FastAPI(title="eucshare")

@app.get("/health")
def health():
    return {"ok": True, "rooms": registry.count(), "sockets": registry.socket_count()}

def client_ip(ws: WebSocket) -> str:
    """Caller address for the per-ip caps. nginx sets X-Real-IP from $remote_addr, which a
    client cannot forge; X-Forwarded-For is not used because nginx appends to whatever the
    client sent, so its first hop is attacker-controlled. If eucshare.ried.no is ever moved
    behind the Cloudflare proxy, nginx must set X-Real-IP from CF-Connecting-IP instead."""
    real = ws.headers.get("x-real-ip", "").strip()
    if real:
        return real
    return ws.client.host if ws.client else ""

@app.websocket("/ws/{room_id}")
async def ws_room(ws: WebSocket, room_id: str):
    if not ROOM_ID.match(room_id):
        await ws.close(code=1008); return
    await ws.accept()
    ip = client_ip(ws)
    try:
        room = await registry.join(room_id, ws, ip)
    except PermissionError:
        await ws.close(code=1013); return          # room full, or over a room / ip / rate cap
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

if __name__ == "__main__":            # local run; the droplet uses deploy/eucshare.service
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8006, access_log=False)   # no request log: rooms are private
