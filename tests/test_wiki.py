from __future__ import annotations

import json
from pathlib import Path

from scripts.generate_wiki import build


ROOT = Path(__file__).resolve().parents[1]


def test_wiki_manifest_and_generation(tmp_path: Path) -> None:
    manifest = json.loads((ROOT / "docs/wiki-manifest.json").read_text(encoding="utf-8"))
    generated = build(
        ROOT / "docs/wiki-manifest.json",
        tmp_path,
        "2.0.0",
        "2.0.0",
        "0123456789abcdef0123456789abcdef01234567",
    )
    names = {path.name for path in generated}
    assert {"Home.md", "_Sidebar.md", "_Footer.md"} <= names
    for page in manifest["pages"]:
        if page["public"]:
            assert f"{page['slug']}.md" in names
            text = (tmp_path / f"{page['slug']}.md").read_text(encoding="utf-8")
            assert "Direct Wiki edits are unsupported" in text
            assert "0123456789abcdef" in text


def test_sidebar_only_contains_public_pages(tmp_path: Path) -> None:
    manifest = json.loads((ROOT / "docs/wiki-manifest.json").read_text(encoding="utf-8"))
    build(ROOT / "docs/wiki-manifest.json", tmp_path, "2.0.0", "2.0.0", "abc")
    sidebar = (tmp_path / "_Sidebar.md").read_text(encoding="utf-8")
    for page in manifest["pages"]:
        assert (f"({page['slug']})" in sidebar) is bool(page["public"])
