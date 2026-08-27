"""Regression test: simulate the _find_item race and assert tag-add is retried.

The implementer's fix queues a deferred tag and retries via threading.Timer.
This test proves whether the queue actually works end-to-end.
"""
import os
import time

os.environ.setdefault("JF_URL", "http://localhost:8096")
os.environ.setdefault("JF_API_KEY", "test-key")

import bridge


def test_retry_queue_add_does_not_deadlock():
    """add() must return promptly."""
    q = bridge.RetryQueue(max_size=10)
    item = bridge.RetryItem("Some Movie", 2024, "Movie", ["1-tag"])
    result = q.add(item)
    assert result is True, "add() should enqueue and return True"
    if q.timer is not None:
        q.timer.cancel()


def test_deferred_tag_is_retried(monkeypatch):
    """Full race: _find_item returns None once, then an item; assert tag-add."""
    calls = {"find": 0, "posted": []}
    fake_item = {"Id": "jf-123", "ProductionYear": 2024, "Tags": []}

    def fake_find(title, year, kind):
        calls["find"] += 1
        if calls["find"] == 1:
            return None
        return fake_item

    monkeypatch.setattr(bridge, "_find_item", fake_find)
    monkeypatch.setattr(
        bridge, "_post_item_tags", lambda item_id, tags: calls["posted"].append((item_id, tags))
    )
    monkeypatch.setattr(bridge.RetryQueue, "_next_delay", lambda self: 0)

    q = bridge.RetryQueue(max_size=10)
    item = bridge.RetryItem("Race Movie", 2024, "Movie", ["1-richard"])
    assert q.add(item) is True

    deadline = time.time() + 5
    while time.time() < deadline and not calls["posted"]:
        time.sleep(0.05)

    assert calls["find"] >= 2, "retry should call _find_item again"
    assert calls["posted"] == [("jf-123", ["1-richard"])], "tag-add must be attempted"