"""Unit tests for Constellation client.py."""

from __future__ import annotations

from constellation.config import load_client_settings
from constellation.client import (
    ConstellationAPIClient,
    ConstellationAPIError,
    default_agent_name,
)


def test_default_agent_name():
    name = default_agent_name()
    assert len(name) > 0
    assert ":" in name


def test_client_headers_and_urls():
    settings = load_client_settings(overrides={"api_base_url": "http://localhost:8080", "token": "secret-token"})
    client = ConstellationAPIClient(settings)

    headers = client._headers()
    assert headers["Authorization"] == "Bearer secret-token"
    assert headers["Accept"] == "application/json"

    url = client._api_url("/topics")
    assert url == "http://localhost:8080/api/v1/topics"
