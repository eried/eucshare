# eucshare

Tiny end-to-end-encrypted relay for EUC Planet live location share
(`eucshare.ried.no`). Riders share a link `https://eucplanet.ried.no/share#roomId.key`;
positions are AES-GCM encrypted with the key from the URL fragment, so this relay
only ever forwards ciphertext. Rooms live in memory and are deleted 2 minutes after
the last connection closes (a reconnect grace, not a rejoin window). No accounts,
no database, no request log.

Limits (all env-overridable, see `config.py`): 200 rooms, 32 peers per room, 6
sockets per client IP, 10 new rooms per IP per minute, 2048 byte messages.

Run: `pip install -r requirements.txt && uvicorn main:app --port 8006 --no-access-log`.
Tests: `pytest`. Deploy: `scripts/deploy.sh` (same pattern as eucstats).
