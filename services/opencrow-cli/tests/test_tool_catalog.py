"""Unit tests for tool_catalog.py."""

from __future__ import annotations

import os
from pathlib import Path
import pytest

from tool_catalog import (
    load_catalog,
    catalog_home,
    state_path,
    quoted_array,
    normalize_toolboxes,
    normalize_tools,
    Catalog,
)


def test_load_catalog():
    catalog = load_catalog()
    assert isinstance(catalog, Catalog)
    assert len(catalog.toolboxes) > 0
    assert len(catalog.tools) > 0
    assert "opencrow-crypto-toolbox" in catalog.toolboxes


def test_catalog_home(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCROW_HOME", str(tmp_path))
    assert catalog_home() == tmp_path


def test_state_path(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCROW_HOME", str(tmp_path))
    catalog = load_catalog()
    sp = state_path(catalog)
    assert sp == tmp_path / catalog.raw["state_relpath"]


def test_quoted_array():
    assert quoted_array(["a", "b c"]) == "(a 'b c')"


def test_normalize_toolboxes():
    catalog = load_catalog()
    all_tb = normalize_toolboxes(catalog, None)
    assert len(all_tb) == len(catalog.toolboxes)

    selected = normalize_toolboxes(catalog, ["opencrow-crypto-toolbox"])
    assert selected == ["opencrow-crypto-toolbox"]

    with pytest.raises(SystemExit):
        normalize_toolboxes(catalog, ["invalid-toolbox-id"])


def test_normalize_tools():
    catalog = load_catalog()
    all_tools = normalize_tools(catalog, None)
    assert all_tools == []

    selected = normalize_tools(catalog, ["angr"])
    assert selected == ["angr"]

    with pytest.raises(SystemExit):
        normalize_tools(catalog, ["nonexistent-tool-id"])
