import pytest
import main

@pytest.fixture(autouse=True)
def clean_registry():
    """The registry is process-global, so every test starts and ends with an empty one."""
    def reset():
        reg = main.registry
        reg.rooms.clear(); reg.ip_sockets.clear(); reg.ip_new_rooms.clear(); reg.socket_ip.clear()
    reset()
    yield
    reset()
