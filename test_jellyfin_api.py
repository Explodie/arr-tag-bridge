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