from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import split_components


def git(repo, *args):
    return subprocess.check_output(["git", *args], cwd=repo, text=True, stderr=subprocess.DEVNULL).strip()


@pytest.fixture
def component_repo(tmp_path, monkeypatch):
    repo = tmp_path / "source"
    repo.mkdir()
    git(repo, "init", "-q")
    for name in ("skills/example/SKILL.md", "packages/mcp/core/server.py"):
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("first revision\n")
    git(repo, "add", ".")
    git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "components")
    monkeypatch.setattr(split_components, "ROOT", repo)
    return repo


def test_paired_splits_match_source_and_publish_together(component_repo, tmp_path):
    repo = component_repo
    manifest = split_components.build("HEAD")
    source = git(repo, "rev-parse", "HEAD")
    assert manifest["source_commit"] == source
    remote = tmp_path / "remote.git"
    git(repo, "init", "--bare", str(remote))
    for component in manifest["components"].values():
        assert git(repo, "rev-parse", component["commit"] + "^{tree}") == git(repo, "rev-parse", source + ":" + component["prefix"])
    split_components.publish(manifest, str(remote))
    for component in manifest["components"].values():
        assert git(remote, "rev-parse", "refs/heads/" + component["branch"]) == component["commit"]


def test_mismatched_component_tree_is_rejected_before_push(component_repo, tmp_path):
    manifest = split_components.build("HEAD")
    manifest["components"]["mcp"]["commit"] = manifest["components"]["skills"]["commit"]
    with pytest.raises(ValueError, match="tree does not match"):
        split_components.publish(manifest, str(tmp_path / "unused-remote"))


def test_release_component_publication_is_gated():
    workflow = (ROOT / ".github/workflows/deploy-release.yml").read_text()
    assert workflow.index("split_components.py build") < workflow.index("--component-revisions")
    assert workflow.index("bash scripts/test_release_installation.sh") < workflow.index("split_components.py publish")
    assert workflow.index("split_components.py publish") < workflow.index("Create draft GitHub Release")


def test_release_manifest_rejects_component_source_skew(tmp_path, monkeypatch):
    import build_releases
    path = tmp_path / "revisions.json"
    path.write_text(json.dumps({"source_commit": "old-source", "components": {"skills": {}, "mcp": {}}}))
    monkeypatch.setattr(sys, "argv", ["build_releases.py", "--source-sha", "new-source", "--component-revisions", str(path)])
    with pytest.raises(ValueError, match="release source commit"):
        build_releases.main()
