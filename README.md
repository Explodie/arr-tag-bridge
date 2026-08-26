# arr-tag-bridge

Syncs Radarr/Sonarr requester tags into Jellyfin.

Triggered by *arr webhook on Import/Upgrade. Reads tags from Radarr/Sonarr API, writes them into Jellyfin as item tags.

## How it works

```
Jellyseerr → Radarr (tags: "13 - Alice")
                  │  webhook on Import/Upgrade
                  ▼
         arr-tag-bridge:5055
                  │  Jellyfin API
                  ▼
              Jellyfin  (tags visible in UI)
```

## Setup

### 1. Add to your docker-compose.yml

```yaml
arr-tag-bridge:
  image: ghcr.io/explodie/arr-tag-bridge:latest
  container_name: arr-tag-bridge
  restart: unless-stopped
  environment:
    - JF_URL=http://jellyfin:8096
    - JF_API_KEY=your_jellyfin_api_key
    - RADARR_URL=http://radarr:7878
    - RADARR_API_KEY=your_radarr_api_key
    - SONARR_URL=http://sonarr:8989
    - SONARR_API_KEY=your_sonarr_api_key
  networks:
    - your_arr_network
```

Omit `SONARR_URL` / `SONARR_API_KEY` if you don't use Sonarr.

### 2. Get API keys

- **Jellyfin**: Dashboard → API Keys → "+" → name it "arr-tag-bridge"
- **Radarr**: Settings → General → API Key
- **Sonarr**: Settings → General → API Key

### 3. Configure webhooks

**Radarr**: Settings → Connect → "+" → Webhook
- URL: `http://arr-tag-bridge:5055/radarr`
- ✓ On Import Complete
- ✓ On Upgrade

**Sonarr**: Same but URL: `http://arr-tag-bridge:5055/sonarr`

### 4. Bring it up

```bash
docker compose pull arr-tag-bridge
docker compose up -d arr-tag-bridge
docker compose logs arr-tag-bridge
```

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `JF_URL` | Yes | Jellyfin server URL |
| `JF_API_KEY` | Yes | Jellyfin API key |
| `RADARR_URL` | Yes | Radarr server URL |
| `RADARR_API_KEY` | Yes | Radarr API key |
| `SONARR_URL` | No | Sonarr server URL |
| `SONARR_API_KEY` | No | Sonarr API key |
| `PORT` | No | Listen port (default 5055) |

## Verifying

Request something in Jellyseerr. After Radarr imports it:

```bash
docker compose logs arr-tag-bridge | tail -10
```

Should show:
```
Radarr Download — 'Movie Title' (2024)
Tags: ['13 - Alice']
✓ Movie Title — 1 tag(s)
```

Then in Jellyfin: movie → Edit Metadata → Tags → "13 - Alice" is there.