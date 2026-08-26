# arr-tag-bridge

Syncs Radarr/Sonarr requester tags into Jellyfin.

Triggered by *arr webhook on Import/Upgrade. Reads tags from Radarr/Sonarr API, writes them into Jellyfin as item tags.

## How it works

```
Jellyseerr → Radarr (tags: "13 - Alice")
                  │  webhook on Import/Upgrade
                  ▼
         arr-tag-bridge:5056
                  │  Jellyfin API
                  ▼
              Jellyfin  (tags visible in UI)
```

## Setup

### 1. Clone the repo

```bash
git clone git@github.com:Explodie/arr-tag-bridge.git
# or HTTPS: git clone https://github.com/Explodie/arr-tag-bridge.git
```

### 2. Add to your docker-compose.yml

```yaml
arr-tag-bridge:
  build: ./arr-tag-bridge
  container_name: arr-tag-bridge
  restart: unless-stopped
  env_file: .env
  networks:
    - your_arr_network
```

Omit `SONARR_URL` / `SONARR_API_KEY` if you don't use Sonarr.

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env: fill in JF_API_KEY, RADARR_API_KEY, SONARR_API_KEY
```

### 4. Get API keys

- **Jellyfin**: Dashboard → API Keys → "+" → name it "arr-tag-bridge"
- **Radarr**: Settings → General → API Key
- **Sonarr**: Settings → General → API Key

### 5. Configure webhooks

**Radarr**: Settings → Connect → "+" → Webhook
- URL: `http://arr-tag-bridge:5056/radarr`
- ✓ On Import Complete
- ✓ On Upgrade

**Sonarr**: Same but URL: `http://arr-tag-bridge:5056/sonarr`

### 6. Bring it up

```bash
docker compose up -d --build arr-tag-bridge
```

### Updating

```bash
cd arr-tag-bridge && git pull && cd .. && docker compose up -d --build arr-tag-bridge
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
| `PORT` | No | Listen port (default 5056) |

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