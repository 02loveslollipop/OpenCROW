from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.generate_wiki import build
from scripts.publish_wiki import WikiPublishError, publish


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


def _seed_wiki_remote(tmp_path: Path) -> tuple[Path, str]:
    remote = tmp_path / "wiki.git"
    checkout = tmp_path / "seed"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "clone", str(remote), str(checkout)], check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-b", "master"], cwd=checkout, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=checkout, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=checkout, check=True)
    (checkout / "Old.md").write_text("previous stable wiki\n")
    subprocess.run(["git", "add", "Old.md"], cwd=checkout, check=True)
    subprocess.run(["git", "commit", "-m", "seed"], cwd=checkout, check=True, capture_output=True)
    subprocess.run(["git", "push", "origin", "master"], cwd=checkout, check=True, capture_output=True)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=checkout, text=True).strip()
    return remote, commit


def test_wiki_publish_is_idempotent_and_failure_preserves_remote(tmp_path: Path) -> None:
    generated = tmp_path / "generated"
    build(ROOT / "docs/wiki-manifest.json", generated, "2.0.0", "2.0.0", "a" * 40)
    remote, old_commit = _seed_wiki_remote(tmp_path)
    with pytest.raises(WikiPublishError, match="Injected failure"):
        publish(
            generated,
            str(remote),
            version="2.0.0",
            source_sha="a" * 40,
            inject_failure="before-push",
        )
    assert subprocess.check_output(
        ["git", "--git-dir", str(remote), "rev-parse", "master"], text=True
    ).strip() == old_commit

    first = publish(generated, str(remote), version="2.0.0", source_sha="a" * 40)
    second = publish(generated, str(remote), version="2.0.0", source_sha="a" * 40)
    assert first["changed"] is True
    assert second["changed"] is False
    assert second["commit"] == first["commit"]


def test_release_workflow_scopes_dedicated_wiki_ssh_credential() -> None:
    workflow = (ROOT / ".github/workflows/deploy-release.yml").read_text(encoding="utf-8")
    assert "WIKI_DEPLOY_SSH_KEY: ${{ secrets.WIKI_DEPLOY_SSH_KEY }}" in workflow
    assert "WIKI_DEPLOY_TOKEN" not in workflow
    assert "git@github.com:02loveslollipop/OpenCROW.wiki.git" in workflow
    assert "github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqq" in workflow


def test_release_workflow_deploys_and_verifies_production_installer_pointers() -> None:
    workflow = (ROOT / ".github/workflows/deploy-release.yml").read_text(encoding="utf-8")
    assert "pages deploy dist-pages --project-name opencrow --branch main" in workflow
    assert "https://opencrow.02labs.me/$name?release=$GITHUB_REF_NAME" in workflow
    assert 'cmp -s "dist-pages/$name" "$downloaded"' in workflow
