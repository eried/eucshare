"""eucshare relay settings (env-overridable, mirrors eucstats config.py)."""
import os

ROOM_TTL_S = int(os.environ.get("EUCSHARE_ROOM_TTL_S", "120"))    # reconnect grace after the last socket closes
MAX_PEERS = int(os.environ.get("EUCSHARE_MAX_PEERS", "32"))
MAX_ROOMS = int(os.environ.get("EUCSHARE_MAX_ROOMS", "1000"))     # live rooms in the whole registry
MAX_CONN_PER_IP = int(os.environ.get("EUCSHARE_MAX_CONN_PER_IP", "24"))  # a household shares one ip: phones, browsers, watchers
NEW_ROOMS_PER_IP_PER_MIN = int(os.environ.get("EUCSHARE_NEW_ROOMS_PER_IP_PER_MIN", "10"))
MAX_MSG_BYTES = int(os.environ.get("EUCSHARE_MAX_MSG_BYTES", "2048"))
MAX_CT_CHARS = int(os.environ.get("EUCSHARE_MAX_CT_CHARS", "1600"))  # ciphertext length inside an envelope
RATE_PER_S = float(os.environ.get("EUCSHARE_RATE_PER_S", "4"))
PEERS_FRAME_S = int(os.environ.get("EUCSHARE_PEERS_FRAME_S", "10"))  # how often the relay reports peer ages
