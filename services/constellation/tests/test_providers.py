from __future__ import annotations

from pathlib import Path

import pytest

from constellation.config import load_runtime_settings
from constellation.providers import (
    Availability,
    AntigravityAdapter,
    ClaudeAdapter,
    OpenCodeAdapter,
    _compatibility,
    extract_session_id,
)
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


@pytest.mark.parametrize(
    ("detected", "expected"),
    [
        ("codex 0.115.9", "incompatible"),
        ("codex 0.116.0", "compatible"),
        ("codex 0.117.0", "compatible"),
        ("codex 0.116.0-rc.1", "incompatible"),
        ("development", "unknown"),
    ],
)
def test_runtime_provider_version_compatibility(detected: str, expected: str) -> None:
    assert _compatibility(detected, "0.116.0")[0] == expected


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


class _FixtureResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.closed = False

    def iter_content(self, chunk_size: int = 65536):
        del chunk_size
        yield self.body

    def close(self) -> None:
        self.closed = True


class _FixtureTurn:
    provider_session_id = "replacement-session"

    def stream(self):
        yield {"session_id": self.provider_session_id, "final_response": "checkpointed"}

    def interrupt(self) -> None:
        pass


class _RecoveryAdapter:
    def availability(self) -> Availability:
        return Availability("opencode", True, "opencode", "1.2.3", "1.0.0", "compatible")

    def resume(self, **_kwargs):
        raise RuntimeError("native session was lost")

    def start(self, **_kwargs):
        return _FixtureTurn()

    @staticmethod
    def extract_session_id(event):
        return event.get("session_id")


def test_lost_provider_session_records_failure_and_saves_replacement_id(tmp_path: Path) -> None:
    socket = RuntimeSocket.__new__(RuntimeSocket)
    socket.runtime_id = "fixture-runtime"
    socket.adapters = {"opencode": _RecoveryAdapter()}
    socket.active_turns = {}
    sent: list[dict] = []
    socket._send = sent.append
    socket._upload_lifecycle_artifacts = lambda **_kwargs: None
    (tmp_path / "CHALLENGE.md").write_text("# Challenge\n")
    (tmp_path / "FINDINGS.md").write_text("# Findings\n")
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n")
    (tmp_path / "HANDOFF.md").write_text(
        "# Handoff\n\n### Evidence\nold\n\n### Failures\nnone\n\n### Artifacts\nold\n\n"
        "### Reproduce\nold\n\n### Exact next actions\ncontinue\n"
    )
    socket._run_provider_turn(
        challenge_id="challenge",
        agent_id="agent",
        provider="opencode",
        prompt="continue",
        workspace=tmp_path,
        model=None,
        provider_session_id="lost-session",
    )
    changelog = (tmp_path / "CHANGELOG.md").read_text()
    assert "native session was lost" in changelog
    assert "replacement session" in changelog
    assert any(item.get("event_type") == "provider_session_resume_failed" for item in sent)
    assert any(item.get("provider_session_id") == "replacement-session" for item in sent)


def test_slave_lifecycle_documents_are_namespaced_and_read_only(tmp_path: Path) -> None:
    socket = RuntimeSocket.__new__(RuntimeSocket)
    responses: list[_FixtureResponse] = []

    class Client:
        @staticmethod
        def list_agents(_challenge_id):
            return {
                "agents": [
                    {"id": "master", "role": "master"},
                    {"id": "slave-one", "role": "slave"},
                ]
            }

        @staticmethod
        def list_agent_artifacts(_agent_id):
            return {
                "artifacts": [
                    {"name": "FINDINGS.md", "file_id": "finding"},
                    {"name": "notes.txt", "file_id": "ignored"},
                ]
            }

        @staticmethod
        def _request(_method, path, stream=False):
            assert path == "/agent-artifacts/finding" and stream is True
            response = _FixtureResponse(b"# Slave findings\n")
            responses.append(response)
            return response

    socket.client = Client()
    socket._send = lambda _payload: None
    socket._materialize_slave_documents("challenge", "master", tmp_path)
    finding = tmp_path / ".opencrow/slaves/slave-one/FINDINGS.md"
    assert finding.read_text() == "# Slave findings\n"
    assert finding.stat().st_mode & 0o222 == 0
    assert not (finding.parent / "notes.txt").exists()
    assert responses[0].closed is True


def test_all_present_lifecycle_documents_are_uploaded_as_artifacts(tmp_path: Path) -> None:
    socket = RuntimeSocket.__new__(RuntimeSocket)
    uploaded: list[str] = []
    events: list[dict] = []

    class Client:
        @staticmethod
        def upload_agent_artifacts(_agent_id, candidates, artifact_type):
            assert artifact_type == "lifecycle"
            uploaded.extend(path.name for path in candidates)
            return {"artifacts": uploaded}

    socket.client = Client()
    socket._send = events.append
    for name in ("CHALLENGE.md", "FINDINGS.md", "CHANGELOG.md", "HANDOFF.md", "WRITEUP.md"):
        (tmp_path / name).write_text(name)
    socket._upload_lifecycle_artifacts(agent_id="agent", challenge_id="challenge", workspace=tmp_path)
    assert uploaded == ["CHALLENGE.md", "FINDINGS.md", "CHANGELOG.md", "HANDOFF.md", "WRITEUP.md"]
    assert events[0]["event_type"] == "lifecycle_artifacts_uploaded"
