from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_release_workflow_gates_publication_on_real_provider_runtime_skills() -> None:
    workflow = (ROOT / ".github/workflows/deploy-release.yml").read_text(encoding="utf-8")
    assert "actions/setup-node@v7" in workflow
    assert "npm install --global @openai/codex opencode-ai @anthropic-ai/claude-code" in workflow
    assert "https://antigravity.google/cli/install.sh" in workflow
    runtime_gate = "bash scripts/test_provider_runtime_skills.sh dist/opencrow-skills.zip"
    assert runtime_gate in workflow
    assert workflow.index("Build verified release assets") < workflow.index(runtime_gate)
    assert workflow.index(runtime_gate) < workflow.index("Create draft GitHub Release")


def test_scheduled_provider_workflow_uses_the_release_runtime_gate() -> None:
    workflow = (ROOT / ".github/workflows/provider-compatibility.yml").read_text(encoding="utf-8")
    assert "python scripts/build_releases.py --allow-development-placeholders" in workflow
    assert "bash scripts/test_provider_runtime_skills.sh dist/opencrow-skills.zip" in workflow
