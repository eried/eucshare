import asyncio, os, importlib

def test_room_deleted_after_ttl_and_reconnect_cancels(monkeypatch):
    monkeypatch.setenv("EUCSHARE_ROOM_TTL_S", "1")
    import config; importlib.reload(config)
    import relay; importlib.reload(relay)
    reg = relay.RoomRegistry()

    class FakeWs:
        async def send_text(self, t): pass

    async def run():
        ws = FakeWs()
        room = await reg.join("R" * 22, ws)
        room.latest["A"] = '{"from":"A","ct":"x"}'
        await reg.leave("R" * 22, ws)
        assert reg.count() == 1                # still there right after leave
        await asyncio.sleep(0.3)
        await reg.join("R" * 22, FakeWs())     # reconnect inside the window cancels the timer
        await asyncio.sleep(1.2)
        assert reg.count() == 1                # NOT deleted: someone is connected
        assert reg.rooms["R" * 22].latest["A"] == '{"from":"A","ct":"x"}'  # envelopes survived
        # now leave for real and let it expire
        for s in list(reg.rooms["R" * 22].sockets):
            await reg.leave("R" * 22, s)
        await asyncio.sleep(1.3)
        assert reg.count() == 0
    asyncio.run(run())
