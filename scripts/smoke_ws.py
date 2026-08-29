"""End-to-end smoke test against the live eucshare relay over the internet.

Connects two WebSocket clients to the same room, sends an envelope from one,
and asserts the other receives exactly that JSON within 5 seconds.

Usage: python scripts/smoke_ws.py
"""
import asyncio
import json
import sys

import websockets

URL = "wss://eucshare.ried.no/ws/AAAAAAAAAAAAAAAAAAAAAA"
MSG = {"from": "A", "ct": "smoke"}
TIMEOUT_S = 5


async def recv_envelope(ws):
    """Skip periodic peers-frames and return the first envelope with a 'ct' field."""
    while True:
        raw = await ws.recv()
        data = json.loads(raw)
        if "ct" in data:
            return data


async def main():
    async with websockets.connect(URL) as a, websockets.connect(URL) as b:
        await a.send(json.dumps(MSG))
        received = await asyncio.wait_for(recv_envelope(b), timeout=TIMEOUT_S)
        assert received == MSG, f"expected {MSG}, got {received}"
        print("SMOKE_OK")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"SMOKE_FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
