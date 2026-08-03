from __future__ import annotations

from pathlib import Path

import pytest

from constellation.config import load_runtime_settings
from constellation.providers import AntigravityAdapter, ClaudeAdapter, OpenCodeAdapter, extract_session_id
from constellation.runtime import RuntimeSocket


def test_provider_commands_use_native_full_auto_and_resume(tmp_path: Path) -> None:
    opencode = OpenCodeAdapter()
    command = opencode.start_command(prompt="solve", workspace=tmp_path, model="vendor/model")
    assert command[:4] == ["opencode", "run", "--format", "json"]
    assert "--auto" in command
    assert "--session" in opencode.resume_command(
        session_id="oc-session", prompt="continue", workspace=tmp_path, model=None
    )

    claude = ClaudeAdapter()
    command = claude.resume_command(session_id="claude-session", prompt="continue", workspace=tmp_path, model=None)
    assert "--dangerously-skip-permissions" in command
    assert command[command.index("--resume") + 1] == "claude-session"

    antigravity = AntigravityAdapter()
    command = antigravity.resume_command(session_id="agy-session", prompt="continue", workspace=tmp_path, model=None)
    assert "--conversation" in command
    assert "--dangerously-skip-permissions" in command


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        ({"session_id": "one"}, "one"),
        ({"event": {"sessionID": "two"}}, "two"),
        ({"result": [{"conversationId": "three"}]}, "three"),
        ({"thread_id": "four"}, "four"),
    ],
)
def test_provider_session_id_extraction(event: dict, expected: str) -> None:
    assert extract_session_id(event) == expected


def test_runtime_settings_are_provider_neutral(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCROW_RUNTIME_PROVIDERS", "opencode,claude")
    monkeypatch.setenv("OPENCROW_RUNTIME_DEFAULT_PROVIDER", "opencode")
    monkeypatch.setenv("OPENCROW_RUNTIME_PROVIDER_MODELS", '{"opencode":"openai/gpt"}')
    settings = load_runtime_settings()
    assert settings.supported_providers == ("opencode", "claude")
    assert settings.default_provider == "opencode"
    assert settings.provider_models == {"opencode": "openai/gpt"}
    assert not hasattr(settings, "codex_model")


def test_lifecycle_phase_is_file_driven(tmp_path: Path) -> None:
    assert RuntimeSocket._lifecycle_phase(tmp_path) == "reconnaissance"
    (tmp_path / "HANDOFF.md").write_text("# Handoff\ncheckpoint")
    assert RuntimeSocket._lifecycle_phase(tmp_path) == "solving"
    (tmp_path / "WRITEUP.md").write_text("# Writeup\nverified")
    assert RuntimeSocket._lifecycle_phase(tmp_path) == "completed"


def test_archive_paths_cannot_escape_workspace(tmp_path: Path) -> None:
    assert RuntimeSocket._safe_archive_destination(tmp_path, "inside/file") == tmp_path / "inside/file"
    with pytest.raises(RuntimeError):
        RuntimeSocket._safe_archive_destination(tmp_path, "../outside")
    with pytest.raises(RuntimeError):
        RuntimeSocket._safe_archive_destination(tmp_path, "/absolute")


def test_dashboard_recon_turn_requires_current_documents(tmp_path: Path) -> None:
    for name, body in {
        "FINDINGS.md": "# Findings\n",
        "CHANGELOG.md": "# Changelog\n",
    }.items():
        (tmp_path / name).write_text(body)
    previous = RuntimeSocket._document_versions(tmp_path)
    (tmp_path / "FINDINGS.md").write_text("# Findings\n\n## F-0001 — Header\n")
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n\n## A-0001 — now\n")
    (tmp_path / "HANDOFF.md").write_text(
        "# Handoff\n\n### Evidence\nF-0001\n\n### Failures\nNone\n\n### Artifacts\ntarget\n\n"
        "### Reproduce\nfile target\n\n### Exact next actions\nDisassemble\n"
    )
    blockers = RuntimeSocket._lifecycle_blockers(
        tmp_path,
        "solving",
        started_phase="reconnaissance",
        previous_versions=previous,
    )
    assert blockers == []
    blockers = RuntimeSocket._lifecycle_blockers(
        tmp_path,
        "completed",
        started_phase="reconnaissance",
        previous_versions=previous,
    )
    assert any("only the handoff phase" in blocker for blocker in blockers)
