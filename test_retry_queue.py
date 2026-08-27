"""Regression test: simulate the _find_item race and assert tag-add is retried.

The implementer's fix queues a deferred tag and retries via threading.Timer.
This test proves whether the queue actually works end-to-end.
"""
import os

os.environ.setdefault("JF_URL", "http://localhost:8096")
os.environ.setdefault("JF_API_KEY", "test-key")

import bridge


def test_retry_queue_add_does_not_deadlock():
    """add() must return promptly.

    bridge.RetryQueue.add() calls self._schedule_next() while holding
    self.lock (a non-reentrant threading.Lock). _schedule_next() then does
    `with self.lock` again -> same-thread deadlock. If this test hangs,
    the lock is non-reentrant and the retry mechanism is broken.
    """
    q = bridge.RetryQueue(max_size=10)
    item = bridge.RetryItem("Some Movie", 2024, "Movie", ["tag-a"])
    result = q.add(item)
    assert result is True, "add() should enqueue and return True"
    # cancel the 15s retry Timer so this test doesn't leak a non-daemon
    # thread that would keep the process alive (and hit real network) after teardown
    if q.timer is not None:
        q.timer.cancel()


def test_deferred_tag_is_retried(monkeypatch):
    """Full race: _find_item returns None once, then an item; assert tag-add
    is eventually attempted via the retry queue.
    """
    calls = {"find": 0, "added": []}
    fake_item = {"Id": "jf-123", "ProductionYear": 2024}

    def fake_find(title, year, kind):
        calls["find"] += 1
        if calls["find"] == 1:
            return None  # simulate race: not yet in library
        return fake_item

    monkeypatch.setattr(bridge, "_find_item", fake_find)
    monkeypatch.setattr(
        bridge, "_add_tag", lambda item_id, tag: calls["added"].append((item_id, tag))
    )
    # shrink the 15s backoff so the retry fires fast
    monkeypatch.setattr(bridge.RetryQueue, "_next_delay", lambda self: 0)

    q = bridge.RetryQueue(max_size=10)
    item = bridge.RetryItem("Race Movie", 2024, "Movie", ["tag-a"])
    assert q.add(item) is True

    # give the timer thread a moment to fire
    import time

    deadline = time.time() + 5
    while time.time() < deadline and not calls["added"]:
        time.sleep(0.05)

    assert calls["find"] >= 2, "retry should call _find_item again"
    assert calls["added"] == [("jf-123", "tag-a")], "tag-add must be attempted"
