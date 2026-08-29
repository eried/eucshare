# eucshare

Tiny end-to-end-encrypted relay for EUC Planet live location share
(`eucshare.ried.no`). Riders share a link `https://eucplanet.ried.no/share#roomId.key`;
positions are AES-GCM encrypted with the key from the URL fragment, so this relay
only ever forwards ciphertext. Rooms live in memory and are deleted 1 hour after the
last connection closes. No accounts, no database.

Run: `pip install -r requirements.txt && uvicorn main:app --port 8006`. Tests: `pytest`.
Deploy: `scripts/deploy.sh` (same pattern as eucstats).
