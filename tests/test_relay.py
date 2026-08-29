import json
from fastapi.testclient import TestClient
import main

ROOM = "AAAAAAAAAAAAAAAAAAAAAA"  # 22-char base64url shape

def env(sender, ct="x"):
    return json.dumps({"from": sender, "ct": ct})

def test_health():
    c = TestClient(main.app)
    r = c.get("/health")
    assert r.status_code == 200 and r.json()["ok"] is True

def test_fanout_to_other_peers_not_self():
    c = TestClient(main.app)
    with c.websocket_connect(f"/ws/{ROOM}") as a, c.websocket_connect(f"/ws/{ROOM}") as b:
        a.send_text(env("A", "ctA"))
        got = json.loads(b.receive_text())
        assert got == {"from": "A", "ct": "ctA"}
        # A must not get its own message back: send from B and check A only sees B's
        b.send_text(env("B", "ctB"))
        assert json.loads(a.receive_text()) == {"from": "B", "ct": "ctB"}

def test_joiner_gets_latest_envelope_replay():
    c = TestClient(main.app)
    # last char swapped (not appended) to keep the id at the required 22 chars
    room2 = ROOM[:-1] + "2"
    with c.websocket_connect(f"/ws/{room2}") as a:
        a.send_text(env("A", "old"))
        a.send_text(env("A", "new"))
        with c.websocket_connect(f"/ws/{room2}") as b:
            replay = json.loads(b.receive_text())
            assert replay == {"from": "A", "ct": "new"}   # only the latest, once

def test_leave_removes_envelope_and_broadcasts_left():
    c = TestClient(main.app)
    # last char swapped (not appended) to keep the id at the required 22 chars
    room3 = ROOM[:-1] + "3"
    with c.websocket_connect(f"/ws/{room3}") as a, c.websocket_connect(f"/ws/{room3}") as b:
        a.send_text(env("A", "ctA")); b.receive_text()
        a.send_text(json.dumps({"type": "leave", "from": "A"}))
        assert json.loads(b.receive_text()) == {"type": "left", "from": "A"}
        with c.websocket_connect(f"/ws/{room3}") as d:
            # nothing stored for A anymore -> a fresh joiner gets no replay for A
            d.send_text(env("D", "ctD"))
            assert json.loads(b.receive_text()) == {"from": "D", "ct": "ctD"}

def test_bad_room_id_rejected():
    c = TestClient(main.app)
    import pytest
    with pytest.raises(Exception):
        with c.websocket_connect("/ws/not-valid!"):
            pass


def test_client_ip_ignores_spoofed_forwarded_for():
    """A forged X-Forwarded-For must not dodge the per-ip caps: only X-Real-IP counts."""
    from main import client_ip
    class Ws:
        headers = {"x-forwarded-for": "9.9.9.9, 203.0.113.5", "x-real-ip": "203.0.113.5"}
        client = type("C", (), {"host": "127.0.0.1"})()
    assert client_ip(Ws()) == "203.0.113.5"
    Ws.headers = {"x-forwarded-for": "9.9.9.9"}
    assert client_ip(Ws()) == "127.0.0.1"
