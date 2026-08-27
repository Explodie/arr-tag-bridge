# arr-tag-bridge

Syncs Radarr/Sonarr requester tags into Jellyfin.

Two triggers:
- **Webhook** on *arr Import/Upgrade (the fast path).
- **Startup reconcile** — on boot, walks the whole *arr library and makes Jellyfin match.

Only Seerr **requester** tags are managed — label format `{userID}-{DisplayName}`
(e.g. `1-richard`). Every other tag on an item is left untouched.

## How it works

```
Jellyseerr → Radarr (requester tag: "1-richard")
                  │  webhook on Import/Upgrade
                  ▼
         localhost:5056
                  │  Jellyfin API
                  ▼
              Jellyfin  (tag visible in UI)
```

On startup the bridge reconciles: for every Radarr movie / Sonarr series that has
requester tags, it adds any missing ones to the matching Jellyfin item and removes
any requester tags that are no longer on the *arr item. This catches anything the
webhook missed (e.g. tags created before the retry fix).

**Source of truth is *arr.** To remove a requester tag for good, remove it in
Radarr/Sonarr (or Jellyseerr) — the next startup reconcile drops it from Jellyfin.
Deleting it only in Jellyfin will re-add it.

## Setup

### 1. Add to your docker-compose.yml

```yaml
arr-tag-bridge:
  image: ghcr.io/explodie/arr-tag-bridge:latest
  container_name: arr-tag-bridge
  restart: unless-stopped
  network_mode: "service:gluetun"
  depends_on:
    - gluetun
  env_file: .env
```

No `build:` block, no local clone needed — the image is published to GHCR on
every push to `main`.

Omit `SONARR_URL` / `SONARR_API_KEY` if you don't use Sonarr.

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env: fill in JF_API_KEY, RADARR_API_KEY, SONARR_API_KEY
```

### 3. Get API keys

- **Jellyfin**: Dashboard → API Keys → "+" → name it "arr-tag-bridge"
- **Radarr**: Settings → General → API Key
- **Sonarr**: Settings → General → API Key

### 4. Configure webhooks

**Radarr**: Settings → Connect → "+" → Webhook
- URL: `http://localhost:5056/radarr`
- ✓ On Import Complete
- ✓ On Upgrade

**Sonarr**: Same but URL: `http://localhost:5056/sonarr`

### 5. Bring it up

```bash
docker compose pull arr-tag-bridge
docker compose up -d arr-tag-bridge
```

### Updating

```bash
docker compose pull arr-tag-bridge
docker compose up -d arr-tag-bridge
```

That's it — the new image is pulled and the container recreated. Same as every
other published image in your stack.

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `JF_URL` | Yes | Jellyfin server URL |
| `JF_API_KEY` | Yes | Jellyfin API key |
| `RADARR_URL` | Yes | Radarr server URL |
| `RADARR_API_KEY` | Yes | Radarr API key |
| `SONARR_URL` | No | Sonarr server URL |
| `SONARR_API_KEY` | No | Sonarr API key |
| `PORT` | No | Listen port (default 5056) |

## Verifying

Request something in Jellyseerr. After Radarr imports it:

```bash
docker compose logs arr-tag-bridge | tail -10
```

Should show:

```
Radarr Download — 'Movie Title' (2024)
Requester tags: ['1-richard']
✓ Movie Title — 1 tag(s)
```

Then in Jellyfin: movie → Edit Metadata → Tags → "1-richard" is there.

On container start, look for the reconcile summary:

```
Startup backfill complete: 12 items, +3 tags, -1 tags
```
