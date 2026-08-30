"""One test per hardening rule: room cap, per-ip caps, sender binding, payload limits."""
import json
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import config
import main

def room_id(n: int) -> str:
    return f"{n:022d}"                      # 22 digits: a valid room id, distinct per test

def env(sender, ct="x"):
    return json.dumps({"from": sender, "ct": ct})

def connect_code(client, room, headers=None):
    """Connect and return the close code if the relay refuses, or None if the socket stays open."""
    try:
        with client.websocket_connect(f"/ws/{room}", headers=dict(headers or {})) as ws:
            msg = ws.receive()              # a refusal closes at once, otherwise a peers frame arrives
            return msg.get("code") if msg["type"] == "websocket.close" else None
    except WebSocketDisconnect as exc:
        return exc.code

@pytest.fixture
def fast_peers(monkeypatch):
    """Short peers interval so connect_code does not wait 10 s on an accepted socket."""
    monkeypatch.setattr(config, "PEERS_FRAME_S", 0.05)

def test_room_cap_blocks_new_rooms_not_joins(monkeypatch, fast_peers):
    monkeypatch.setattr(config, "MAX_ROOMS", 1)
    c = TestClient(main.app)
    with c.websocket_connect(f"/ws/{room_id(1)}"):
        assert connect_code(c, room_id(2)) == 1013     # the registry is full: no second room
        assert connect_code(c, room_id(1)) is None     # joining the existing room still works

def test_socket_cap_per_ip(monkeypatch, fast_peers):
    monkeypatch.setattr(config, "MAX_CONN_PER_IP", 2)
    c = TestClient(main.app)
    mine = {"x-real-ip": "9.9.9.9"}                 # nginx sets X-Real-IP from $remote_addr
    room = room_id(3)
    with c.websocket_connect(f"/ws/{room}", headers=dict(mine)), \
         c.websocket_connect(f"/ws/{room}", headers=dict(mine)):
        assert connect_code(c, room, mine) == 1013                        # a third socket
        assert connect_code(c, room, {"x-real-ip": "9.9.9.8"}) is None    # another ip is free
    assert main.registry.ip_sockets == {}              # every disconnect path decrements

def test_new_room_rate_per_ip(monkeypatch, fast_peers):
    monkeypatch.setattr(config, "NEW_ROOMS_PER_IP_PER_MIN", 2)
    c = TestClient(main.app)
    mine = {"x-real-ip": "5.5.5.5"}
    for n in (10, 11):
        assert connect_code(c, room_id(n), mine) is None   # two creations inside the window
    assert connect_code(c, room_id(12), mine) == 1013      # a third new room is refused
    assert connect_code(c, room_id(10), mine) is None      # joining a live room is not creating
    assert connect_code(c, room_id(12), {"x-real-ip": "5.5.5.6"}) is None   # per ip, not global

def test_socket_is_bound_to_its_first_sender_id():
    c = TestClient(main.app)
    room = room_id(4)
    with c.websocket_connect(f"/ws/{room}") as a, c.websocket_connect(f"/ws/{room}") as b:
        a.send_text(env("A", "one"))
        assert json.loads(b.receive_text()) == {"from": "A", "ct": "one"}
        a.send_text(env("SPOOF", "two"))                 # a second id on the same socket: dropped
        a.send_text(env("A", "three"))
        assert json.loads(b.receive_text()) == {"from": "A", "ct": "three"}   # SPOOF never arrived
        b.send_text(json.dumps({"from": "B" * 33, "ct": "long-id"}))          # invalid id: dropped
        b.send_text(env("B", "ok"))
        assert json.loads(a.receive_text()) == {"from": "B", "ct": "ok"}
        assert sorted(main.registry.rooms[room].latest) == ["A", "B"]

def test_disconnect_emits_left_and_clears_latest():
    c = TestClient(main.app)
    room = room_id(5)
    with c.websocket_connect(f"/ws/{room}") as b:
        with c.websocket_connect(f"/ws/{room}") as a:
            a.send_text(env("A", "ctA"))
            assert json.loads(b.receive_text()) == {"from": "A", "ct": "ctA"}
            a.close(1000)                    # disconnect inside the block: the relay reacts first
            assert json.loads(b.receive_text()) == {"type": "left", "from": "A"}
        assert main.registry.rooms[room].latest == {}
        assert main.registry.rooms[room].last_seen == {}
        with c.websocket_connect(f"/ws/{room}") as d:
            b.send_text(env("B", "ctB"))     # d's first frame is B's, so nothing stale was replayed
            assert json.loads(d.receive_text()) == {"from": "B", "ct": "ctB"}

def test_oversize_or_non_string_ct_dropped():
    c = TestClient(main.app)
    room = room_id(6)
    with c.websocket_connect(f"/ws/{room}") as a, c.websocket_connect(f"/ws/{room}") as b:
        a.send_text(env("A", "x" * (config.MAX_CT_CHARS + 1)))   # over the ct limit, under MAX_MSG_BYTES
        a.send_text(json.dumps({"from": "A", "ct": 12345}))      # not a string
        a.send_text(env("A", "ok"))
        assert json.loads(b.receive_text()) == {"from": "A", "ct": "ok"}   # only the valid one relayed
        assert main.registry.rooms[room].latest["A"] == env("A", "ok")

def test_health_reports_open_sockets():
    c = TestClient(main.app)
    assert c.get("/health").json() == {"ok": True, "rooms": 0, "sockets": 0}
    with c.websocket_connect(f"/ws/{room_id(7)}"):
        assert c.get("/health").json() == {"ok": True, "rooms": 1, "sockets": 1}


def test_reconnect_with_same_sender_keeps_presence():
    """The old socket of a rider who reconnected under the same id closes without a left frame."""
    client = TestClient(main.app)
    room = room_id(77)
    env = json.dumps({"from": "rider-stable", "ct": "AAAA"})
    with client.websocket_connect(f"/ws/{room}") as watcher:
        old = client.websocket_connect(f"/ws/{room}"); old.__enter__(); old.send_text(env)
        assert json.loads(watcher.receive_text())["from"] == "rider-stable"
        new = client.websocket_connect(f"/ws/{room}"); new.__enter__(); new.send_text(env)
        assert json.loads(watcher.receive_text())["from"] == "rider-stable"
        old.__exit__(None, None, None)                    # the stale socket goes away
        # the room still lists the rider and the watcher gets no "left"
        r = main.registry.rooms[room]
        assert "rider-stable" in r.latest and "rider-stable" in r.senders.values()
        new.send_text(env)
        assert json.loads(watcher.receive_text()).get("type") != "left"
        new.__exit__(None, None, None)
