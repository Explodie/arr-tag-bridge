"""Tests for requester-tag detection and startup reconcile.

Only Seerr requester tags ("{userID}-{DisplayName}", e.g. "1-richard") are ever
touched. Reconcile must add missing, remove stale, and leave non-requester tags
strictly alone.
"""
import os

os.environ.setdefault("JF_URL", "http://localhost:8096")
os.environ.setdefault("JF_API_KEY", "test-key")

import bridge


# ── _is_requester_tag ────────────────────────────────────────────────

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


# ── _reconcile_item ──────────────────────────────────────────────────

def test_reconcile_adds_missing_requester_tags(monkeypatch):
    monkeypatch.setattr(bridge, "_find_item", lambda t, y, k: {"Id": "jf-1"})
    monkeypatch.setattr(bridge, "_jf_item_tags", lambda iid: {"1-richard"})
    added, removed = [], []
    monkeypatch.setattr(bridge, "_add_tag", lambda iid, tag: added.append((iid, tag)))
    monkeypatch.setattr(bridge, "_remove_tag", lambda iid, tag: removed.append((iid, tag)))

    a, r = bridge._reconcile_item("Movie", 2024, "Movie", ["1-richard", "2-bob"])

    assert (a, r) == (1, 0)
    assert added == [("jf-1", "2-bob")]
    assert removed == []


def test_reconcile_removes_stale_requester_tags(monkeypatch):
    monkeypatch.setattr(bridge, "_find_item", lambda t, y, k: {"Id": "jf-1"})
    monkeypatch.setattr(bridge, "_jf_item_tags", lambda iid: {"1-richard", "3-carol"})
    added, removed = [], []
    monkeypatch.setattr(bridge, "_add_tag", lambda iid, tag: added.append(tag))
    monkeypatch.setattr(bridge, "_remove_tag", lambda iid, tag: removed.append(tag))

    a, r = bridge._reconcile_item("Movie", 2024, "Movie", ["1-richard"])

    assert (a, r) == (0, 1)
    assert added == []
    assert removed == ["3-carol"]


def test_reconcile_ignores_non_requester_tags(monkeypatch):
    monkeypatch.setattr(bridge, "_find_item", lambda t, y, k: {"Id": "jf-1"})
    # "favorite" is a manual Jellyfin tag — must never be touched
    monkeypatch.setattr(bridge, "_jf_item_tags", lambda iid: {"1-richard", "favorite"})
    added, removed = [], []
    monkeypatch.setattr(bridge, "_add_tag", lambda iid, tag: added.append(tag))
    monkeypatch.setattr(bridge, "_remove_tag", lambda iid, tag: removed.append(tag))

    a, r = bridge._reconcile_item("Movie", 2024, "Movie", ["2-bob"])

    assert added == ["2-bob"]
    assert removed == ["1-richard"]
    assert "favorite" not in added and "favorite" not in removed


def test_reconcile_item_not_found_is_noop(monkeypatch):
    monkeypatch.setattr(bridge, "_find_item", lambda t, y, k: None)
    added, removed = [], []
    monkeypatch.setattr(bridge, "_add_tag", lambda iid, tag: added.append(tag))
    monkeypatch.setattr(bridge, "_remove_tag", lambda iid, tag: removed.append(tag))

    a, r = bridge._reconcile_item("Movie", 2024, "Movie", ["1-richard"])

    assert (a, r) == (0, 0)
    assert added == [] and removed == []
