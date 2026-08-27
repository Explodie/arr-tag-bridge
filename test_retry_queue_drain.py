"""Regression: queue must drain past the first item.

After _retry_next() succeeds (or gives up) it must schedule the NEXT queued
item. If it returns without _schedule_next(), items 2..N sit in the queue
forever (timer is already None after pop).
"""
import os

os.environ.setdefault("JF_URL", "http://localhost:8096")
os.environ.setdefault("JF_API_KEY", "test-key")

import time

import bridge


def test_queue_drains_all_items_on_success(monkeypatch):
    """Two items queued; _find_item succeeds -> BOTH must get tag-add."""
    added = []

    fake_item = {"Id": "jf-123", "ProductionYear": 2024}

    monkeypatch.setattr(bridge, "_find_item", lambda title, year, kind: fake_item)
    monkeypatch.setattr(
        bridge, "_add_tag", lambda item_id, tag: added.append((item_id, tag))
    )
    monkeypatch.setattr(bridge.RetryQueue, "_next_delay", lambda self: 0)

    q = bridge.RetryQueue(max_size=10)
    q.add(bridge.RetryItem("Movie One", 2024, "Movie", ["tag-a"]))
    q.add(bridge.RetryItem("Movie Two", 2024, "Movie", ["tag-b"]))

    deadline = time.time() + 5
    while time.time() < deadline and len(added) < 2:
        time.sleep(0.05)

    assert len(added) == 2, f"expected both items drained, got {added}"
    assert q.queue == [], f"queue should be empty after drain, got {q.queue}"


def test_queue_drains_after_give_up(monkeypatch):
    """Two items, _find_item always returns None -> both must be given up."""
    attempts = {"count": 0}

    def fake_find(title, year, kind):
        attempts["count"] += 1
        return None

    monkeypatch.setattr(bridge, "_find_item", fake_find)
    monkeypatch.setattr(bridge.RetryQueue, "_next_delay", lambda self: 0)

    q = bridge.RetryQueue(max_size=10)
    q.add(bridge.RetryItem("Movie One", 2024, "Movie", ["tag-a"]))
    q.add(bridge.RetryItem("Movie Two", 2024, "Movie", ["tag-b"]))

    # Each item gets up to 3 attempts (attempt 0,1,2) before giving up.
    # Give-up path must then schedule the next item.
    deadline = time.time() + 5
    while time.time() < deadline and attempts["count"] < 6:
        time.sleep(0.05)

    assert attempts["count"] >= 6, (
        f"expected 2 items x 3 attempts = 6 _find_item calls, got {attempts['count']}"
    )
    assert q.queue == [], f"queue should be empty after both give up, got {q.queue}"
