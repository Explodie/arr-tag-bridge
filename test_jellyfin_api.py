"""Test Jellyfin API calls with mocks.  Jellyfin 10.11: only search + POST /Items/{id}."""
import os

os.environ.setdefault("JF_URL", "http://localhost:8096")
os.environ.setdefault("JF_API_KEY", "test-key")

import pytest
from unittest.mock import patch, Mock
import requests

import bridge


# -- _find_item --------------------------------------------------------

def test_find_item_includes_fields_tags():
    """_find_item sends fields=Tags to get tags in search result."""
    with patch('bridge.requests.get') as mock_get:
        mock_resp = Mock()
        mock_resp.json.return_value = {"Items": [{"Id": "abc", "Tags": ["1-richard"]}]}
        mock_get.return_value = mock_resp

        item = bridge._find_item("The Patriot", 2000, "Movie")
        assert item is not None
        assert item["Tags"] == ["1-richard"]

        _, kwargs = mock_get.call_args
        assert kwargs["params"]["fields"] == "Tags"
        assert "api_key" in kwargs["params"]


# -- _merge_tags_for_item ----------------------------------------------

def test_merge_tags_preserves_non_requester():
    """Non-requester tags pass through unchanged."""
    result = bridge._merge_tags_for_item(
        ["genre-action", "1-richard"],
        ["2-alice"],
        [],
    )
    assert "genre-action" in result
    assert "1-richard" in result
    assert "2-alice" in result


def test_merge_tags_removes_stale():
    result = bridge._merge_tags_for_item(
        ["1-richard", "2-alice"],
        [],
        ["1-richard"],
    )
    assert "1-richard" not in result
    assert "2-alice" in result


def test_merge_tags_idempotent():
    result = bridge._merge_tags_for_item(
        ["1-richard"],
        ["1-richard"],
        [],
    )
    assert result == ["1-richard"]


# -- _post_item_tags ---------------------------------------------------

def test_post_item_tags_sends_tags_array():
    with patch('bridge.requests.post') as mock_post:
        mock_resp = Mock()
        mock_post.return_value = mock_resp

        bridge._post_item_tags("item-123", ["1-richard", "2-alice"])

        _, kwargs = mock_post.call_args
        assert kwargs["json"]["Tags"] == ["1-richard", "2-alice"]
        assert kwargs["json"]["Id"] == "item-123"


def test_post_item_tags_raises_on_error():
    http_error = requests.HTTPError("400 Bad Request")
    http_error.response = Mock(status_code=400)

    with patch('bridge.requests.post') as mock_post:
        mock_post.side_effect = http_error
        with pytest.raises(requests.HTTPError):
            bridge._post_item_tags("bad-id", [])