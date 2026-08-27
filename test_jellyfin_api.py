"""Test Jellyfin API calls with mocks."""
import os

os.environ.setdefault("JF_URL", "http://localhost:8096")
os.environ.setdefault("JF_API_KEY", "test-key")

import pytest
from unittest.mock import patch, Mock

import bridge


def test_jf_item_tags_no_fields_param():
    """Verify _jf_item_tags doesn't send 'fields=Tags' param."""
    with patch('bridge.requests.get') as mock_get:
        mock_resp = Mock()
        mock_resp.json.return_value = {"Tags": ["1-richard", "2-alice"]}
        mock_get.return_value = mock_resp

        tags = bridge._jf_item_tags("test-id")
        assert tags == {"1-richard", "2-alice"}

        # Verify no 'fields' param sent
        _, kwargs = mock_get.call_args
        assert "fields" not in kwargs["params"]
        assert "api_key" in kwargs["params"]