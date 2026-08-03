from __future__ import annotations

import json
from pathlib import Path

import pytest

from opencrow_lifecycle.engine import LifecycleError, WorkflowEngine
from opencrow_lifecycle import hooks
from opencrow_lifecycle.hooks import handle
from opencrow_lifecycle.init_cli import provider_command
from opencrow_lifecycle.mcp_server import StdioServer, call_tool
from opencrow_lifecycle.search_policy import is_target_writeup_search


def initialized(tmp_path: Path) -> WorkflowEngine:
    engine = WorkflowEngine(tmp_path)
    engine.initialize("AcmeCTF Orbital Lock: recover the flag from service.bin", provider="codex")
    return engine


def test_initialization_creates_only_pre_handoff_documents(tmp_path: Path) -> None:
    engine = initialized(tmp_path)
    assert engine.phase == "reconnaissance"
    assert (tmp_path / "CHALLENGE.md").is_file()
    assert (tmp_path / "FINDINGS.md").is_file()
    assert (tmp_path / "CHANGELOG.md").is_file()
    assert not (tmp_path / "HANDOFF.md").exists()
    assert not (tmp_path / "WRITEUP.md").exists()
    assert engine.enforcement == "strict"


def test_original_challenge_is_immutable_and_clarifications_append(tmp_path: Path) -> None:
    engine = initialized(tmp_path)
    engine.add_clarification("The service listens on 31337.", source="organizer", evidence="ticket #4")
    engine.verify_original_challenge()
    challenge = (tmp_path / "CHALLENGE.md").read_text()
    assert "ticket #4" in challenge
    (tmp_path / "CHALLENGE.md").write_text(challenge.replace("recover the flag", "do something else"))
    with pytest.raises(LifecycleError, match="immutable"):
        engine.verify_original_challenge()


def test_phase_transitions_and_append_only_history(tmp_path: Path) -> None:
    engine = initialized(tmp_path)
    first = engine.record_finding(title="Format", finding="ELF x86-64", evidence="file service.bin")
    assert first["finding_id"] == "F-0001"
    second = engine.record_finding(
        finding_id="F-0001",
        title="Format correction",
        finding="ELF AArch64",
        evidence="readelf -h service.bin",
        status="superseded",
        supersedes="F-0001",
    )
    assert second["finding_id"] == "F-0001"
    engine.record_attempt(
        hypothesis="Binary is unpacked",
        action="Inspect headers",
        command="readelf -h service.bin",
        outcome="AArch64 ELF",
        evidence="saved readelf.txt",
        status="succeeded",
        next_action="Disassemble main",
    )
    engine.update_handoff(
        summary="Architecture identified",
        evidence="F-0001 and readelf.txt",
        failures="No dynamic run on x86 host",
        artifacts="service.bin, readelf.txt",
        reproduce="readelf -h service.bin",
        next_actions="1. Run qemu-aarch64. 2. Trace input parser.",
    )
    assert engine.phase == "solving"
    assert engine.validate_completion().valid
    engine.writeup(
        title="Verified solve",
        summary="Recover key",
        solution="Invert the parser transform.",
        reproduce="python3 solve.py",
        evidence="service prints accepted",
        flag="flag{test}",
    )
    assert engine.phase == "completed"
    assert not engine.validate_completion(solved=True).valid
    assert "only one phase" in " ".join(engine.validate_completion(solved=True).blockers)
    engine.initialize("AcmeCTF Orbital Lock: recover the flag from service.bin", provider="codex")
    engine.writeup(
        title="Independent verification",
        summary="Rechecked the solve",
        solution="Repeated the parser inversion.",
        reproduce="python3 solve.py",
        evidence="service prints accepted again",
        verification="Verified in a fresh invocation.",
    )
    assert engine.validate_completion(solved=True).valid


def test_stale_handoff_and_writeup_are_blocked(tmp_path: Path) -> None:
    engine = initialized(tmp_path)
    engine.record_finding(title="Format", finding="ELF", evidence="file target")
    engine.record_attempt(
        hypothesis="ELF is native",
        action="Inspect",
        command="file target",
        outcome="ELF",
        evidence="file output",
        status="succeeded",
        next_action="Disassemble",
    )
    engine.update_handoff(
        summary="Ready", evidence="F-0001", failures="None", artifacts="target",
        reproduce="file target", next_actions="Disassemble main",
    )
    engine.record_finding(title="Late", finding="PIE", evidence="readelf")
    assert "stale" in " ".join(engine.validate_completion().blockers)
    engine.update_handoff(
        summary="Updated", evidence="F-0001 and F-0002", failures="None", artifacts="target",
        reproduce="readelf -h target", next_actions="Disassemble main",
    )
    engine.initialize("AcmeCTF Orbital Lock: recover the flag from service.bin", provider="codex")
    engine.writeup(title="Solve", summary="Done", solution="Invert", reproduce="python solve.py", evidence="accepted")
    assert engine.validate_completion(solved=True).valid
    engine.record_attempt(
        hypothesis="Verify again", action="Run solver", command="python solve.py", outcome="accepted",
        evidence="stdout", status="succeeded", next_action="Update verification",
    )
    assert "stale" in " ".join(engine.validate_completion(solved=True).blockers)


def test_recon_stop_is_blocked_but_interrupt_is_not(tmp_path: Path) -> None:
    initialized(tmp_path)
    code, result = handle("stop", "claude", {}, tmp_path)
    assert code == 2
    assert result["decision"] == "block"
    code, result = handle("stop", "claude", {"reason": "user interruption"}, tmp_path)
    assert code == 0
    assert result["continue"] is True


def test_warn_and_off_enforcement(tmp_path: Path) -> None:
    engine = initialized(tmp_path)
    config = engine.read_config()
    config["enforcement"] = "warn"
    engine.config_path.write_text(json.dumps(config))
    validation = engine.validate_completion()
    assert validation.valid and validation.warnings
    config["enforcement"] = "off"
    engine.config_path.write_text(json.dumps(config))
    validation = engine.validate_completion()
    assert validation.valid and not validation.warnings


def test_direct_append_is_accepted_and_destructive_edit_is_snapshotted(tmp_path: Path) -> None:
    engine = initialized(tmp_path)
    findings = tmp_path / "FINDINGS.md"
    original = findings.read_text()
    findings.write_text(original + "\n## F-0001 — Direct\n\n- Status: `confirmed`\n")
    assert engine.reconcile_history().valid
    state = json.loads(engine.state_path.read_text())
    accepted = tmp_path / ".opencrow" / state["accepted_documents"]["FINDINGS.md"]["snapshot"]
    assert accepted.read_text() == findings.read_text()

    findings.write_text("# Findings\n\nreplacement\n")
    validation = engine.reconcile_history()
    assert not validation.valid
    assert "discarded or replaced" in " ".join(validation.blockers)
    rejected = state = json.loads(engine.state_path.read_text())
    rejected_path = tmp_path / ".opencrow" / rejected["rejected_documents"]["FINDINGS.md"]["snapshot"]
    assert rejected_path.read_text() == findings.read_text()
    assert accepted.read_text().startswith(original)


def test_destructive_direct_edit_warns_or_logs_when_configured(tmp_path: Path) -> None:
    engine = initialized(tmp_path)
    findings = tmp_path / "FINDINGS.md"
    findings.write_text("destroyed\n")
    config = engine.read_config()
    config["enforcement"] = "warn"
    engine.config_path.write_text(json.dumps(config))
    validation = engine.reconcile_history()
    assert validation.valid and validation.warnings
    code, response = handle("post_tool", "codex", {"tool_name": "edit"}, tmp_path)
    assert code == 0 and response["warnings"]
    config["enforcement"] = "off"
    engine.config_path.write_text(json.dumps(config))
    validation = engine.reconcile_history()
    assert validation.valid and not validation.warnings
    events = (tmp_path / ".opencrow/events.jsonl").read_text()
    assert "history_violation" in events


def test_compaction_preserves_invocation_hash_baseline(tmp_path: Path) -> None:
    engine = initialized(tmp_path)
    before = json.loads(engine.state_path.read_text())["invocation"]
    code, _ = handle("compaction", "codex", {}, tmp_path)
    after = json.loads(engine.state_path.read_text())["invocation"]
    assert code == 0
    assert before == after


def test_old_recon_evidence_cannot_complete_a_new_invocation(tmp_path: Path) -> None:
    engine = initialized(tmp_path)
    engine.record_finding(title="Format", finding="ELF", evidence="file target")
    engine.record_attempt(
        hypothesis="Native", action="Inspect", command="file target", outcome="ELF",
        evidence="stdout", status="succeeded", next_action="handoff",
    )
    engine.begin_invocation(phase="reconnaissance")
    engine.update_handoff(
        summary="Old evidence", evidence="F-0001", failures="None", artifacts="target",
        reproduce="file target", next_actions="Disassemble",
    )
    blockers = " ".join(engine.validate_completion().blockers)
    assert "current-invocation FINDINGS.md" in blockers
    assert "current-invocation CHANGELOG.md" in blockers


def test_hook_failure_is_visible_and_fails_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    initialized(tmp_path)
    (tmp_path / ".opencrow/config.json").write_text("not json")
    monkeypatch.setattr("sys.argv", ["opencrow-lifecycle-hook", "session_start", "--workspace", str(tmp_path)])
    monkeypatch.setattr("sys.stdin", type("Input", (), {"read": lambda self: "{}"})())
    assert hooks.main() == 0
    response = json.loads(capsys.readouterr().out)
    assert response["continue"] is True
    assert "failed open" in response["warning"]
    assert (tmp_path / ".opencrow/diagnostics.log").is_file()


def test_mcp_lists_seven_tools_and_records(tmp_path: Path) -> None:
    initialized(tmp_path)
    server = StdioServer(tmp_path)
    listing = server.dispatch({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert listing is not None
    assert len(listing["result"]["tools"]) == 7
    result = call_tool(
        "workflow_record_finding",
        {"title": "Header", "finding": "ELF", "evidence": "file output"},
        tmp_path,
    )
    assert result["isError"] is False


def test_target_search_policy_allows_general_research() -> None:
    challenge = "## Original Challenge\nAcmeCTF Orbital Lock service.bin"
    assert is_target_writeup_search("AcmeCTF Orbital Lock writeup", challenge)
    assert is_target_writeup_search("CTF challenge solution flag", challenge)
    assert not is_target_writeup_search("Python pathlib documentation", challenge)
    assert not is_target_writeup_search("integer optimization algorithm solution", challenge)


@pytest.mark.parametrize(
    ("provider", "binary", "unsafe_flag"),
    [
        ("codex", "codex", "--dangerously-bypass-approvals-and-sandbox"),
        ("opencode", "opencode", "--auto"),
        ("claude", "claude", "--dangerously-skip-permissions"),
        ("antigravity", "agy", "--dangerously-skip-permissions"),
    ],
)
def test_provider_commands_use_native_unsafe_flags(provider: str, binary: str, unsafe_flag: str, tmp_path: Path) -> None:
    safe = provider_command(provider, prompt="go", workspace=tmp_path, model="test-model", unsafe=False)
    unsafe = provider_command(provider, prompt="go", workspace=tmp_path, model=None, unsafe=True)
    assert safe[0] == binary
    assert unsafe_flag not in safe
    assert unsafe_flag in unsafe
