from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from installer import opencrow_manager
from opencrow_lifecycle import __version__
from opencrow_lifecycle.mcp_server import StdioServer
from scripts import build_releases, generate_wiki


def test_release_version_is_consistent(monkeypatch) -> None:
    manifest = json.loads((ROOT / "installer/manifests/release.json").read_text(encoding="utf-8"))
    expected = manifest["version"]

    monkeypatch.setattr(sys, "argv", ["build_releases.py"])
    build_version = build_releases.parse_args().version
    monkeypatch.setattr(sys, "argv", ["generate_wiki.py"])
    wiki_version = generate_wiki.parse_args().version

    response = StdioServer(ROOT).dispatch({"id": 1, "method": "initialize", "params": {}})
    assert response is not None
    mcp_version = response["result"]["serverInfo"]["version"]

    assert expected == "2.1.2"
    assert {opencrow_manager.VERSION, __version__, mcp_version, build_version, wiki_version} == {expected}
