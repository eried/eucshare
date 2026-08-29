"""eucshare relay settings (env-overridable, mirrors eucstats config.py)."""
import os

ROOM_TTL_S = int(os.environ.get("EUCSHARE_ROOM_TTL_S", "3600"))   # delete a room 1 h after its last socket closes
MAX_PEERS = int(os.environ.get("EUCSHARE_MAX_PEERS", "32"))
MAX_MSG_BYTES = int(os.environ.get("EUCSHARE_MAX_MSG_BYTES", "2048"))
RATE_PER_S = float(os.environ.get("EUCSHARE_RATE_PER_S", "4"))
PEERS_FRAME_S = int(os.environ.get("EUCSHARE_PEERS_FRAME_S", "10"))  # how often the relay reports peer ages
