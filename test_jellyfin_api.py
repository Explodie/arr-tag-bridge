"""Test Jellyfin API calls with mocks."""
import os

os.environ.setdefault("JF_URL", "http://localhost:8096")
os.environ.setdefault("JF_API_KEY", "test-key")

import pytest
from unittest.mock import patch, Mock
import requests

import bridge


def test_jf_item_tags_normal():
    """_jf_item_tags returns tag names from the item object."""
    with patch('bridge.requests.get') as mock_get:
        mock_resp = Mock()
        mock_resp.json.return_value = {"Tags": ["1-richard", "2-alice"]}
        mock_get.return_value = mock_resp

        tags = bridge._jf_item_tags("test-id")
        assert tags == {"1-richard", "2-alice"}

        _, kwargs = mock_get.call_args
        assert "fields" not in kwargs["params"]
        assert "api_key" in kwargs["params"]


def test_jf_item_tags_400_returns_empty():
    """_jf_item_tags returns empty set on 400 — doesn't crash reconcile."""
    http_error = requests.HTTPError("400 Bad Request")
    http_error.response = Mock(status_code=400)

    with patch('bridge.requests.get') as mock_get:
        mock_get.side_effect = http_error
        tags = bridge._jf_item_tags("bad-id")
        assert tags == set()


def test_jf_tags_404_returns_empty():
    """_jf_tags returns empty dict on 404 — doesn't crash reconcile."""
    # Reset cache so we hit the endpoint
    with patch.object(bridge, '_tag_cache', None):
        http_error = requests.HTTPError("404 Not Found")
        http_error.response = Mock(status_code=404)

        with patch('bridge.requests.get') as mock_get:
            mock_get.side_effect = http_error
            tags = bridge._jf_tags()
            assert tags == {}


def test_ensure_tag_post_404_returns_none():
    """_ensure_tag returns None when POST /Tags 404s."""
    http_error = requests.HTTPError("404 Not Found")
    http_error.response = Mock(status_code=404)

    with patch.object(bridge, '_tag_cache', None):
        with patch('bridge.requests.get') as mock_get:
            # _jf_tags also 404s -> empty dict
            mock_get.side_effect = http_error
            with patch('bridge.requests.post') as mock_post:
                mock_post.side_effect = http_error
                tid = bridge._ensure_tag("1-richard")
                assert tid is None


def test_add_tag_fallback_uses_tagname():
    """_add_tag uses tagName param when _ensure_tag returns None."""
    with patch.object(bridge, '_ensure_tag', return_value=None):
        with patch('bridge.requests.post') as mock_post:
            mock_resp = Mock()
            mock_post.return_value = mock_resp

            bridge._add_tag("item-123", "1-richard")

            _, kwargs = mock_post.call_args
            assert kwargs["params"]["tagName"] == "1-richard"
            assert "tagId" not in kwargs["params"]