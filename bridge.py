"""
arr-tag-bridge: Syncs Radarr/Sonarr requester tags into Jellyfin.
Triggered by *arr webhook on Import/Upgrade; also reconciles on startup.

Listens on :5056. Radarr → /radarr, Sonarr → /sonarr.
Config via env vars (see README).

Only Seerr "requester" tags are managed — label format "{userID}-{DisplayName}"
(e.g. "1-richard"). Every other tag on an item is left untouched.
"""

import os
import re
import logging
import requests
import time
import threading
from flask import Flask, request, jsonify
from typing import NamedTuple

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

# ── requester-tag detection ──────────────────────────────────────────
# Seerr tags look like "{userID}-{DisplayName}", e.g. "1-richard".
# The bridge only manages tags matching this pattern — everything else is ignored.
REQUESTER_TAG_RE = re.compile(r"^\d+-")


def _is_requester_tag(name: str) -> bool:
    return bool(REQUESTER_TAG_RE.match(name))


# ── retry queue ────────────────────────────────────────────────────

class RetryItem(NamedTuple):
    title: str
    year: int | None
    kind: str
    tag_names: list[str]

class RetryQueue:
    def __init__(self, max_size=100):
        self.queue: list[tuple[RetryItem, int]] = []  # (item, attempt)
        self.lock = threading.RLock()
        self.max_size = max_size
        self.timer = None

    def add(self, item: RetryItem) -> bool:
        """Add item to queue. Returns False if queue full."""
        with self.lock:
            if len(self.queue) >= self.max_size:
                log.error("Retry queue full — dropping deferred tag for '%s'", item.title)
                return False
            self.queue.append((item, 0))
            self._schedule_next()
            return True

    def _schedule_next(self) -> None:
        """Schedule next retry if not already pending."""
        with self.lock:
            if self.timer or not self.queue:
                return
            delay = self._next_delay()
            self.timer = threading.Timer(delay, self._retry_next)
            self.timer.start()
            log.debug("Scheduled retry in %.1f seconds", delay)

    def _next_delay(self) -> int:
        """Backoff: 15s → 45s → 2m."""
        if not self.queue:
            return 0
        _, attempt = self.queue[0]
        return [15, 45, 120][min(attempt, 2)]

    def _retry_next(self) -> None:
        """Process next item in queue."""
        with self.lock:
            if not self.queue:
                self.timer = None
                return

            item, attempt = self.queue.pop(0)
            self.timer = None

        # Re-attempt outside lock to avoid holding during I/O
        try:
            log.info("Retry #%d for '%s'", attempt + 1, item.title)
            found = _find_item(item.title, item.year, item.kind)
            if found:
                for tag in item.tag_names:
                    _add_tag(found["Id"], tag)
                log.info("✓ Retry success for '%s'", item.title)
                self._schedule_next()
                return

            # Still missing — requeue or give up
            with self.lock:
                if attempt < 2:
                    self.queue.append((item, attempt + 1))
                    log.warning("'%s' still not found — will retry again", item.title)
                    self._schedule_next()
                else:
                    log.error("'%s' failed after %d retries — giving up", item.title, attempt + 1)
                    self._schedule_next()
        except Exception as e:
            log.error("Retry failed for '%s': %s", item.title, e)
            with self.lock:
                self.queue.append((item, attempt))  # Try again later
                self._schedule_next()

retry_queue = RetryQueue()

# simple in-memory cache for tag-name → tag-id (busted on create only), with thread-safe access
_tag_cache: dict[str, str] | None = None
_tag_cache_lock = threading.Lock()


# ── jellyfin helpers ──────────────────────────────────────────────────

def _jf_tags() -> dict[str, str]:
    """Return {TagName: TagId} for all Jellyfin tags."""
    global _tag_cache
    with _tag_cache_lock:
        if _tag_cache is not None:
            return _tag_cache

    # New retry logic for API calls
    for attempt in range(3):
        try:
            r = requests.get(f"{JF_URL}/Tags", params={"api_key": JF_API_KEY}, timeout=10)
            r.raise_for_status()
            tags = {t["Name"]: t["Id"] for t in r.json().get("Items", [])}
            with _tag_cache_lock:
                _tag_cache = tags
            return tags
        except requests.RequestException as e:
            if attempt == 2:
                raise
            wait = 1 + (attempt * 2)
            log.warning("Retry #%d/3 for tags fetch in %ds: %s", attempt+1, wait, e)
            time.sleep(wait)
    return {}  # unreachable but keeps type checker happy


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


def _remove_tag(item_id: str, tag_name: str) -> None:
    """Detach a tag from an item (does not delete the tag globally)."""
    tags = _jf_tags()
    tid = tags.get(tag_name)
    if not tid:
        log.warning("Tag '%s' not found in Jellyfin — nothing to remove", tag_name)
        return
    requests.post(
        f"{JF_URL}/Items/{item_id}/Tags/Delete",
        params={"tagId": tid, "api_key": JF_API_KEY},
        timeout=10,
    ).raise_for_status()


def _jf_item_tags(item_id: str) -> set[str]:
    """Return the set of tag names currently on a Jellyfin item."""
    r = requests.get(
        f"{JF_URL}/Items/{item_id}",
        params={"api_key": JF_API_KEY},
        timeout=10,
    )
    r.raise_for_status()
    return set(r.json().get("Tags", []))


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

def _radarr_tag_lut() -> dict[int, str]:
    r = requests.get(f"{RADARR_URL}/api/v3/tag", params={"apikey": RADARR_KEY}, timeout=10)
    r.raise_for_status()
    return {t["id"]: t["label"] for t in r.json()}


def _sonarr_tag_lut() -> dict[int, str]:
    r = requests.get(f"{SONARR_URL}/api/v3/tag", params={"apikey": SONARR_KEY}, timeout=10)
    r.raise_for_status()
    return {t["id"]: t["label"] for t in r.json()}


def _radarr_tag_names(tag_ids: list[int]) -> list[str]:
    if not tag_ids or not RADARR_URL:
        return []
    lut = _radarr_tag_lut()
    return [lut.get(tid, f"tag-{tid}") for tid in tag_ids]


def _sonarr_tag_names(tag_ids: list[int]) -> list[str]:
    if not tag_ids or not SONARR_URL:
        return []
    lut = _sonarr_tag_lut()
    return [lut.get(tid, f"tag-{tid}") for tid in tag_ids]


# ── reconcile + startup backfill ─────────────────────────────────────

def _reconcile_item(title: str, year: int | None, kind: str, desired: list[str]) -> tuple[int, int]:
    """Make the item's requester tags match `desired`. Returns (added, removed).

    Only requester-format tags are ever added or removed; any other tag on the
    Jellyfin item is left alone.
    """
    item = _find_item(title, year, kind)
    if not item:
        log.debug("Backfill: '%s' (%s) not in Jellyfin yet — skipped", title, year)
        return 0, 0

    item_id = item["Id"]
    desired_set = {t for t in desired if _is_requester_tag(t)}
    current = {t for t in _jf_item_tags(item_id) if _is_requester_tag(t)}

    added = removed = 0
    for t in sorted(desired_set - current):
        _add_tag(item_id, t)
        added += 1
    for t in sorted(current - desired_set):
        _remove_tag(item_id, t)
        removed += 1

    if added or removed:
        log.info("Reconcile '%s': +%d -%d", title, added, removed)
    return added, removed


def _backfill_reconcile() -> None:
    """Reconcile requester tags across the whole *arr library (startup)."""
    seen = added = removed = 0

    if RADARR_URL and RADARR_KEY:
        try:
            lut = _radarr_tag_lut()
            r = requests.get(f"{RADARR_URL}/api/v3/movie", params={"apikey": RADARR_KEY}, timeout=30)
            r.raise_for_status()
            for m in r.json():
                names = [lut.get(tid, f"tag-{tid}") for tid in m.get("tags", [])]
                names = [n for n in names if _is_requester_tag(n)]
                if not names:
                    continue
                seen += 1
                a, d = _reconcile_item(m.get("title", "Unknown"), m.get("year"), "Movie", names)
                added += a
                removed += d
        except Exception as e:
            log.error("Radarr backfill failed: %s", e)

    if SONARR_URL and SONARR_KEY:
        try:
            lut = _sonarr_tag_lut()
            r = requests.get(f"{SONARR_URL}/api/v3/series", params={"apikey": SONARR_KEY}, timeout=30)
            r.raise_for_status()
            for s in r.json():
                names = [lut.get(tid, f"tag-{tid}") for tid in s.get("tags", [])]
                names = [n for n in names if _is_requester_tag(n)]
                if not names:
                    continue
                seen += 1
                a, d = _reconcile_item(s.get("title", "Unknown"), s.get("year"), "Series", names)
                added += a
                removed += d
        except Exception as e:
            log.error("Sonarr backfill failed: %s", e)

    log.info("Startup backfill complete: %d items, +%d tags, -%d tags", seen, added, removed)


def _startup_backfill() -> None:
    """Give Jellyfin/*arr a moment to come up, then run the initial reconcile."""
    time.sleep(180)
    _backfill_reconcile()


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

    names = [n for n in _radarr_tag_names(tag_ids) if _is_requester_tag(n)]
    if not names:
        log.info("No requester tags — nothing to sync")
        return jsonify({"status": "ok", "synced": False, "reason": "no requester tags"})
    log.info("Requester tags: %s", names)

    item = _find_item(title, year, "Movie")
    if not item:
        log.warning("'%s' not found in Jellyfin (race with library scan?)", title)
        if not retry_queue.add(RetryItem(title, year, "Movie", names)):
            return jsonify({"status": "failed", "reason": "queue full"})
        return jsonify({"status": "deferred", "reason": "queued for retry"})

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

    names = [n for n in _sonarr_tag_names(tag_ids) if _is_requester_tag(n)]
    if not names:
        log.info("No requester tags — nothing to sync")
        return jsonify({"status": "ok", "synced": False, "reason": "no requester tags"})
    log.info("Requester tags: %s", names)

    item = _find_item(title, year, "Series")
    if not item:
        log.warning("'%s' not found in Jellyfin", title)
        if not retry_queue.add(RetryItem(title, year, "Series", names)):
            return jsonify({"status": "failed", "reason": "queue full"})
        return jsonify({"status": "deferred", "reason": "queued for retry"})

    for tag in names:
        _add_tag(item["Id"], tag)

    log.info("✓ %s — %d tag(s)", title, len(names))
    return jsonify({"status": "ok", "synced": True, "item_id": item["Id"], "tags": names})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5056"))
    log.info("arr-tag-bridge starting on :%d", port)
    threading.Thread(target=_startup_backfill, daemon=True, name="backfill").start()
    app.run(host="0.0.0.0", port=port)
