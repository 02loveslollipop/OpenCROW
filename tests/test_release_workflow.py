from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_release_workflow_gates_publication_on_full_install_and_update() -> None:
    workflow = (ROOT / ".github/workflows/deploy-release.yml").read_text(encoding="utf-8")
    gate = "bash scripts/test_release_installation.sh"
    assert 'tags: ["*.*.*"]' in workflow
    assert "pull_request:" not in workflow and "schedule:" not in workflow
    assert workflow.index("Build verified release assets") < workflow.index("fetch-previous") < workflow.index(gate)
    assert workflow.index(gate) < workflow.index("Retain release installation evidence") < workflow.index("Create draft GitHub Release")
    assert "if: always()" in workflow
    assert '"$RUNNER_TEMP/previous-stable/opencrow-full.zip"' in workflow
    assert "test_provider_runtime_skills.sh" not in workflow
    for name in ("pr-verification.yml", "system-install-matrix.yml", "provider-compatibility.yml"):
        assert gate not in (ROOT / ".github/workflows" / name).read_text()


def test_scheduled_provider_workflow_uses_the_release_runtime_gate() -> None:
    workflow = (ROOT / ".github/workflows/provider-compatibility.yml").read_text(encoding="utf-8")
    assert "python scripts/build_releases.py --allow-development-placeholders" in workflow
    assert "bash scripts/test_provider_runtime_skills.sh dist/opencrow-skills.zip" in workflow
