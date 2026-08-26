"""
arr-tag-bridge: Syncs Radarr/Sonarr tags into Jellyfin.
Triggered by *arr webhook on Import/Upgrade.

Listens on :5055. Radarr → /radarr, Sonarr → /sonarr.
Config via env vars (see README).
"""

import os
import logging
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("arr-tag-bridge")

# ── config from environment ──────────────────────────────────────────
JF_URL      = os.environ["JF_URL"].rstrip("/")       # http://jellyfin:8096
JF_API_KEY  = os.environ["JF_API_KEY"]

RADARR_URL  = os.environ.get("RADARR_URL", "").rstrip("/")
RADARR_KEY  = os.environ.get("RADARR_API_KEY", "")

SONARR_URL  = os.environ.get("SONARR_URL", "").rstrip("/")
SONARR_KEY  = os.environ.get("SONARR_API_KEY", "")

# simple in-memory cache for tag-name → tag-id (busted on create only)
_tag_cache: dict[str, str] | None = None


# ── jellyfin helpers ──────────────────────────────────────────────────

def _jf_tags() -> dict[str, str]:
    """Return {TagName: TagId} for all Jellyfin tags."""
    global _tag_cache
    if _tag_cache is not None:
        return _tag_cache
    r = requests.get(f"{JF_URL}/Tags", params={"api_key": JF_API_KEY}, timeout=10)
    r.raise_for_status()
    _tag_cache = {t["Name"]: t["Id"] for t in r.json().get("Items", [])}
    return _tag_cache


def _ensure_tag(name: str) -> str:
    """Get or create a Jellyfin tag; return its Id."""
    tags = _jf_tags()
    if name in tags:
        return tags[name]
    log.info("Creating Jellyfin tag: %s", name)
    r = requests.post(
        f"{JF_URL}/Tags",
        json={"Name": name},
        params={"api_key": JF_API_KEY},
        headers={"Content-Type": "application/json"},
        timeout=10,
    )
    r.raise_for_status()
    tid: str = r.json()["Id"]
    tags[name] = tid
    return tid


def _add_tag(item_id: str, tag_name: str) -> None:
    tid = _ensure_tag(tag_name)
    requests.post(
        f"{JF_URL}/Items/{item_id}/Tags/Add",
        params={"tagId": tid, "api_key": JF_API_KEY},
        timeout=10,
    ).raise_for_status()


def _find_item(title: str, year: int | None, kind: str):  # -> dict | None
    """Search Jellyfin for a Movie or Series by title + year."""
    params: dict = {
        "searchTerm": title,
        "includeItemTypes": kind,
        "recursive": "true",
        "api_key": JF_API_KEY,
    }
    if year:
        params["years"] = year
    r = requests.get(f"{JF_URL}/Items", params=params, timeout=10)
    r.raise_for_status()
    items: list[dict] = r.json().get("Items", [])
    if not items:
        return None
    # pick exact-year match if available
    for it in items:
        if year and it.get("ProductionYear") == year:
            return it
    return items[0]


# ── *arr tag resolution ───────────────────────────────────────────────

def _radarr_tag_names(tag_ids: list[int]) -> list[str]:
    if not tag_ids or not RADARR_URL:
        return []
    r = requests.get(f"{RADARR_URL}/api/v3/tag", params={"apikey": RADARR_KEY}, timeout=10)
    r.raise_for_status()
    lut = {t["id"]: t["label"] for t in r.json()}
    return [lut.get(tid, f"tag-{tid}") for tid in tag_ids]


def _sonarr_tag_names(tag_ids: list[int]) -> list[str]:
    if not tag_ids or not SONARR_URL:
        return []
    r = requests.get(f"{SONARR_URL}/api/v3/tag", params={"apikey": SONARR_KEY}, timeout=10)
    r.raise_for_status()
    lut = {t["id"]: t["label"] for t in r.json()}
    return [lut.get(tid, f"tag-{tid}") for tid in tag_ids]


# ── webhook handlers ──────────────────────────────────────────────────

@app.route("/radarr", methods=["POST"])
def radarr_webhook():
    body: dict = request.get_json(force=True)

    event: str = body.get("eventType", "")
    movie: dict = body.get("movie", {})
    title: str = movie.get("title", "Unknown")
    year: int | None = movie.get("year")
    movie_id: int = movie.get("id", 0)

    log.info("Radarr %s — '%s' (%s)", event, title, year)

    if event not in ("Download", "Upgrade"):
        return jsonify({"status": "skipped", "event": event})

    if not RADARR_URL:
        return jsonify({"error": "RADARR_URL not configured"}), 500

    # read tags from Radarr API (webhook payload doesn't include them)
    r = requests.get(
        f"{RADARR_URL}/api/v3/movie/{movie_id}",
        params={"apikey": RADARR_KEY},
        timeout=10,
    )
    r.raise_for_status()
    tag_ids: list[int] = r.json().get("tags", [])

    if not tag_ids:
        log.info("No tags — nothing to sync")
        return jsonify({"status": "ok", "synced": False, "reason": "no tags"})

    names = _radarr_tag_names(tag_ids)
    log.info("Tags: %s", names)

    item = _find_item(title, year, "Movie")
    if not item:
        log.warning("'%s' not found in Jellyfin (race with library scan?)", title)
        return jsonify({"status": "deferred", "reason": "not found in Jellyfin"})

    for tag in names:
        _add_tag(item["Id"], tag)

    log.info("✓ %s — %d tag(s)", title, len(names))
    return jsonify({"status": "ok", "synced": True, "item_id": item["Id"], "tags": names})


@app.route("/sonarr", methods=["POST"])
def sonarr_webhook():
    body: dict = request.get_json(force=True)

    event: str = body.get("eventType", "")
    series: dict = body.get("series", {})
    title: str = series.get("title", "Unknown")
    year: int | None = series.get("year")
    series_id: int = series.get("id", 0)

    log.info("Sonarr %s — '%s'", event, title)

    if event not in ("Download", "Upgrade"):
        return jsonify({"status": "skipped", "event": event})

    if not SONARR_URL:
        return jsonify({"error": "SONARR_URL not configured"}), 500

    r = requests.get(
        f"{SONARR_URL}/api/v3/series/{series_id}",
        params={"apikey": SONARR_KEY},
        timeout=10,
    )
    r.raise_for_status()
    tag_ids: list[int] = r.json().get("tags", [])

    if not tag_ids:
        log.info("No tags — nothing to sync")
        return jsonify({"status": "ok", "synced": False, "reason": "no tags"})

    names = _sonarr_tag_names(tag_ids)
    log.info("Tags: %s", names)

    item = _find_item(title, year, "Series")
    if not item:
        log.warning("'%s' not found in Jellyfin", title)
        return jsonify({"status": "deferred", "reason": "not found in Jellyfin"})

    for tag in names:
        _add_tag(item["Id"], tag)

    log.info("✓ %s — %d tag(s)", title, len(names))
    return jsonify({"status": "ok", "synced": True, "item_id": item["Id"], "tags": names})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5055"))
    log.info("arr-tag-bridge starting on :%d", port)
    app.run(host="0.0.0.0", port=port)