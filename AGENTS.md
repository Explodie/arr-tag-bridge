# arr-tag-bridge — AGENTS.md

One-way tag sync: Radarr/Sonarr requester tags → Jellyfin item tags.

## Purpose

Jellyseerr writes a requester tag onto Radarr/Sonarr items. This service mirrors
those tags onto the matching Jellyfin item so the requester is visible in
Jellyfin's UI.

## Scope — requester tags ONLY

Managed tag format: `{userID}-{DisplayName}`, e.g. `1-richard`. Detected by
regex `^\d+-`.

- The bridge may **only** add/remove tags matching that pattern.
- Any other tag on a Jellyfin item is strictly untouched.
- Do not add sync logic for non-requester tags.

## Source of truth

**\*arr is the source of truth. Jellyfin is a mirror.** This is one-way.

- A tag removed only in Jellyfin will be re-added (by startup reconcile or next
  webhook). Durable removal = delete the tag in Radarr/Sonarr/Jellyseerr.
- There is deliberately no reverse sync (Jellyfin → *arr). Jellyfin has no
  "tag removed" webhook, and reverse sync would fight Seerr's own writes.

## Triggers

1. **Webhook** — `/radarr`, `/sonarr` on `Download`/`Upgrade` events. Fast path.
2. **Startup reconcile** — on boot (180s delay), walks all Radarr movies + Sonarr
   series and makes Jellyfin match: adds missing requester tags, removes stale
   requester tags.

## Architecture

- Single file: `bridge.py` (Flask app). Port `5056` (was 5055; clashed with Seerr).
- Stateless: no DB, no volume. Retry queue is in-memory (`RetryQueue`, max 100,
  backoff 15s/45s/2m). A restart loses pending retries — acceptable: scan lag is
  seconds, and losing a pending retry beats silently dropping every racing request.
- `_tag_cache` is a module-level dict guarded by `threading.Lock()`.

## Known pitfalls

- **Item matching is title+year heuristic** (`_find_item`). Remakes/specials can
  mismatch. Reconcile logs only summary counts, so a bad match is quiet — verify
  suspicious items manually.
- **`_jf_tags()` cache is busted only on create** (`_ensure_tag` mutates the
  returned dict). Never add logic that invalidates tags elsewhere without busting
  the cache.
- **Race:** Radarr fires the webhook the moment it imports the file; Jellyfin may
  not have scanned yet. That's what `RetryQueue` exists for. Do not remove it.

## Deployment model

- **Published image on GHCR.** `image: ghcr.io/explodie/arr-tag-bridge:latest`.
  `.github/workflows/publish.yml` builds + pushes on every push to `main`
  (tags: `latest` + git sha + branch/tag). No `build:` block on the host, no
  local clone.
- `network_mode: service:gluetun` — all service URLs are `localhost`.
- Deploy path: push to `main` → CI publishes → `docker compose pull
  arr-tag-bridge && docker compose up -d arr-tag-bridge` on the media server.
- (History: started local-build `build: ./arr-tag-bridge`; reverted to GHCR
  because the media server has no git/build access and every other service in
  the stack pulls from a registry.)

## Files

| File | Role |
|---|---|
| `bridge.py` | Entire app |
| `Dockerfile` | Non-root user + `/health` HEALTHCHECK |
| `requirements.txt` | flask + requests |
| `.env.example` | localhost URLs template |
| `README.md` | User-facing setup/verify |
| `test_retry_queue.py`, `test_retry_queue_drain.py`, `test_reconcile.py` | pytest regression tests |

## Verification

```bash
python3 -m pytest -q
```

All tests must pass before commit. Manual smoke: request in Jellyseerr, watch
`docker compose logs arr-tag-bridge` for the `✓` line, confirm tag in Jellyfin UI.
