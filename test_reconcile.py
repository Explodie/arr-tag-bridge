"""Tests for requester-tag detection and startup reconcile.

Only Seerr requester tags ("{userID}-{DisplayName}", e.g. "1-richard") are
ever touched. Reconcile uses single POST /Items/{itemId} per item (Jellyfin
10.11 model - no per-tag endpoints).
"""
import os

os.environ.setdefault("JF_URL", "http://localhost:8096")
os.environ.setdefault("JF_API_KEY", "test-key")

import bridge


# -- _is_requester_tag -------------------------------------------------

def test_requester_tag_detection():
    assert bridge._is_requester_tag("1-richard") is True
    assert bridge._is_requester_tag("13-richard-smith") is True
    assert bridge._is_requester_tag("42-Alice") is True


def test_requester_tag_rejects_non_matching():
    assert bridge._is_requester_tag("richard") is False
    assert bridge._is_requester_tag("richard-1") is False
    assert bridge._is_requester_tag("-richard") is False
    assert bridge._is_requester_tag("") is False
    assert bridge._is_requester_tag("hd") is False


# -- _reconcile_item ---------------------------------------------------

def test_reconcile_adds_missing_requester_tags(monkeypatch):
    monkeypatch.setattr(
        bridge, "_find_item",
        lambda t, y, k: {"Id": "jf-1", "Tags": ["1-richard"]},
    )
    posted = []
    monkeypatch.setattr(
        bridge, "_post_item_tags",
        lambda item_id, tags: posted.append((item_id, tags)),
    )

    a, r = bridge._reconcile_item("Movie", 2024, "Movie", ["1-richard", "2-bob"])

    assert (a, r) == (1, 0)
    assert posted == [("jf-1", sorted(["1-richard", "2-bob"]))]


def test_reconcile_removes_stale_requester_tags(monkeypatch):
    monkeypatch.setattr(
        bridge, "_find_item",
        lambda t, y, k: {"Id": "jf-1", "Tags": ["1-richard", "3-carol"]},
    )
    posted = []
    monkeypatch.setattr(
        bridge, "_post_item_tags",
        lambda item_id, tags: posted.append((item_id, tags)),
    )

    a, r = bridge._reconcile_item("Movie", 2024, "Movie", ["1-richard"])

    assert (a, r) == (0, 1)
    assert posted == [("jf-1", ["1-richard"])]


def test_reconcile_ignores_non_requester_tags(monkeypatch):
    monkeypatch.setattr(
        bridge, "_find_item",
        lambda t, y, k: {"Id": "jf-1", "Tags": ["1-richard", "favorite"]},
    )
    posted = []
    monkeypatch.setattr(
        bridge, "_post_item_tags",
        lambda item_id, tags: posted.append((item_id, tags)),
    )

    a, r = bridge._reconcile_item("Movie", 2024, "Movie", ["2-bob"])

    assert (a, r) == (1, 1)
    merged = posted[0][1]
    assert "2-bob" in merged
    assert "1-richard" not in merged
    assert "favorite" in merged  # preserved


def test_reconcile_item_not_found_is_noop(monkeypatch):
    monkeypatch.setattr(bridge, "_find_item", lambda t, y, k: None)
    posted = []
    monkeypatch.setattr(
        bridge, "_post_item_tags",
        lambda item_id, tags: posted.append(tags),
    )

    a, r = bridge._reconcile_item("Movie", 2024, "Movie", ["1-richard"])

    assert (a, r) == (0, 0)
    assert posted == []