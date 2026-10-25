"""Reuse verified SDK dependencies while testing isolated installer payloads."""
from pathlib import Path
import pytest


@pytest.fixture(autouse=True)
def sdk_dependencies(monkeypatch):
    modules = Path(__file__).resolve().parents[2] / "packages/opencode/node_modules"
    if (modules / "@opencode/sdk/package.json").is_file():
        monkeypatch.setenv("OPENCROW_OPENCODE_NODE_MODULES", str(modules))
