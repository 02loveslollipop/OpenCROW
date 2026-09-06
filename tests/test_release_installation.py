from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import pytest

from scripts import release_installation as gate

ROOT = Path(__file__).resolve().parents[1]


def bundle(tmp_path, *, extra=None, bad_hash=False):
    files = {
        "release-manifest.json": json.dumps({"schema_version": 2, "install_mode": "full", "version": "2.1.2+candidate", "release_tag": "2.1.2+candidate"}).encode(),
        "installer/install.sh": b"#!/bin/bash\nexit 0\n",
        "installer/opencrow_manager.py": b"candidate manager",
        "skills/example/SKILL.md": b"example skill",
    }
    if extra:
        files.update(extra)
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    if bad_hash:
        hashes["installer/install.sh"] = "0" * 64
    archive = tmp_path / "full.zip"
    with zipfile.ZipFile(archive, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
        z.writestr("checksums.json", json.dumps(hashes))
    return archive


def test_extract_and_installed_payload_integrity(tmp_path):
    source = tmp_path / "source"
    manifest = gate.extract_bundle(bundle(tmp_path), source)
    assert manifest["version"] == "2.1.2+candidate"
    snapshot = tmp_path / "current"
    shutil.copytree(source, snapshot)
    gate.verify_snapshot(source, snapshot)
    (snapshot / "skills/example/SKILL.md").write_text("damaged")
    with pytest.raises(RuntimeError, match="Installed asset differs"):
        gate.verify_snapshot(source, snapshot)


@pytest.mark.parametrize("extra,bad_hash,match", [
    ({"../escape": b"unsafe"}, False, "Unsafe archive"),
    ({"/absolute": b"unsafe"}, False, "Unsafe archive"),
    ({"..\\escape": b"unsafe"}, False, "Unsafe archive"),
    (None, True, "checksum mismatch"),
])
def test_rejects_bundle_before_extracting(tmp_path, extra, bad_hash, match):
    with pytest.raises(RuntimeError, match=match):
        gate.extract_bundle(bundle(tmp_path, extra=extra, bad_hash=bad_hash), tmp_path / "source")
    assert not (tmp_path / "source").exists()


def test_rejects_unlisted_file(tmp_path):
    archive = bundle(tmp_path)
    with zipfile.ZipFile(archive, "a") as z:
        z.writestr("unverified.sh", "exit 0")
    with pytest.raises(RuntimeError, match="inventory"):
        gate.extract_bundle(archive, tmp_path / "source")


def test_previous_release_ignores_candidate_drafts_and_prereleases():
    def release(tag, date, **kwargs):
        return dict(tagName=tag, publishedAt=date, isDraft=False, isPrerelease=False, **kwargs)
    older = release("2.1.0+old", "2026-08-01")
    previous = release("2.1.2+stable", "2026-09-01")
    candidate = release("2.1.3+candidate", "2026-09-06")
    draft = {**candidate, "tagName": "2.1.4", "isDraft": True}
    prerelease = {**candidate, "tagName": "2.1.4-rc1", "isPrerelease": True}
    assert gate.previous_release([older, candidate, draft, prerelease, previous], candidate["tagName"]) == previous["tagName"]
    with pytest.raises(RuntimeError, match="baseline is required"):
        gate.previous_release([candidate, draft, prerelease], candidate["tagName"])


def installation(tmp_path, monkeypatch):
    source = tmp_path / "source"
    gate.extract_bundle(bundle(tmp_path), source)
    providers = {name: {"skills_dir": f".{name}/skills"} for name in gate.PROVIDERS}
    (source / "integrations").mkdir()
    (source / "integrations/manifest.json").write_text(json.dumps({"providers": providers}))
    home = tmp_path / "home"
    data = home / ".local/share/opencrow"
    shutil.copytree(source, data / "current")
    (data / "envs/ctf/bin").mkdir(parents=True)
    (data / "envs/ctf/bin/python").touch()
    state = {"version": "2.1.2", "install_mode": "full", "selected_agents": sorted(gate.PROVIDERS),
             "selected_toolboxes": sorted(gate.TOOLBOXES),
             "package_methods": {"python_environments": {"installed": ["ctf"], "unresolved": []}}}
    state_path = home / ".local/state/opencrow/state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps(state))
    for config in providers.values():
        shutil.copytree(source / "skills", home / config["skills_dir"])
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(gate.shutil, "which", lambda command: f"/usr/bin/{command}")
    calls = []
    doctor = {"ok": True, "mode": "full", "version": "2.1.2", "integrations": [
        {"provider": p, "selected": True, "healthy": True} for p in gate.PROVIDERS]}

    def run(command, report, name, input_text=None):
        calls.append((command, input_text))
        if command == ["opencrow", "doctor"]:
            return json.dumps(doctor)
        if input_text:
            requests = [json.loads(line) for line in input_text.splitlines()]
            assert [r["method"] for r in requests] == ["initialize", "notifications/initialized", "tools/list"]
            return '\n'.join(map(json.dumps, [
                {"id": 1, "result": {"serverInfo": {"name": "fixture", "version": "2.1.2"}}},
                {"id": 2, "result": {"tools": [{"name": "fixture"}]}}]))
        return "fixture version/help/config\n"

    monkeypatch.setattr(gate, "run", run)
    return source, home, state_path, doctor, calls


def test_full_verification_only_boots_and_reads_configuration(tmp_path, monkeypatch):
    source, home, _, _, calls = installation(tmp_path, monkeypatch)
    baseline = tmp_path / "baseline"
    shutil.copytree(source, baseline)
    manifest = gate.read_json(baseline / "release-manifest.json")
    manifest["release_tag"] = "2.1.2+previous"
    (baseline / "release-manifest.json").write_text(json.dumps(manifest))
    (baseline / "installer/opencrow_manager.py").write_text("old manager")
    hashes = gate.read_json(baseline / "checksums.json")
    hashes["installer/opencrow_manager.py"] = gate.digest(baseline / "installer/opencrow_manager.py")
    (baseline / "checksums.json").write_text(json.dumps(hashes))
    shutil.copytree(baseline, home / ".local/share/opencrow/previous")
    shutil.copy(home / ".local/state/opencrow/state.json", home / ".local/state/opencrow/previous-state.json")
    (home / "release-user-data.txt").write_text("preserve me\n")
    (home / ".codex/config.toml").write_text("# release-user-config: preserve me\n")
    gate.verify(source, tmp_path / "reports", baseline)
    assert gate.read_json(tmp_path / "reports/summary.json")["ok"]
    for command, _ in calls:
        assert command[1:] in (["doctor"], ["--version"], ["--help"], ["mcp", "list", "--json"],
                               ["debug", "config"], ["mcp", "list"], ["-m", "pip", "check"], [])
    (home / "release-user-data.txt").unlink()
    with pytest.raises(FileNotFoundError):
        gate.verify(source, tmp_path / "reports-failed", baseline)
    assert not (tmp_path / "reports-failed/summary.json").exists()


@pytest.mark.parametrize("failure", ["doctor", "version", "environment", "skill", "startup"])
def test_failed_installation_or_startup_cannot_pass(tmp_path, monkeypatch, failure):
    source, home, state_path, doctor, _ = installation(tmp_path, monkeypatch)
    if failure == "doctor":
        doctor["ok"] = False
    elif failure in ("version", "environment"):
        state = gate.read_json(state_path)
        if failure == "version":
            state["version"] = "2.1.1"
        else:
            state["package_methods"]["python_environments"]["unresolved"] = ["missing dependency"]
        state_path.write_text(json.dumps(state))
    elif failure == "skill":
        (home / ".claude/skills/example/SKILL.md").unlink()
    else:
        original = gate.run
        def run(command, *args, **kwargs):
            if command == ["claude", "--help"]:
                raise RuntimeError("startup failed")
            return original(command, *args, **kwargs)
        monkeypatch.setattr(gate, "run", run)
    with pytest.raises(RuntimeError):
        gate.verify(source, tmp_path / "reports", None)
    assert not (tmp_path / "reports/summary.json").exists()


def test_command_failures_preserve_logs(tmp_path):
    with pytest.raises(RuntimeError, match="exited 7"):
        gate.run([sys.executable, "-c", "import sys; print('startup error', file=sys.stderr); sys.exit(7)"], tmp_path, "boot")
    assert "startup error" in (tmp_path / "boot.stderr.log").read_text()


def test_probe_timeout_is_bounded(tmp_path, monkeypatch):
    def timeout(command, **kwargs):
        assert kwargs["timeout"] == 120
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])
    monkeypatch.setattr(gate.subprocess, "run", timeout)
    with pytest.raises(subprocess.TimeoutExpired):
        gate.run(["fixture"], tmp_path, "boot")


def test_matrix_continues_after_failure_and_propagates_failure(tmp_path, monkeypatch):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "docker-calls"
    docker = fake_bin / "docker"
    docker.write_text('''#!/bin/bash
printf '%s\\n' "$*" >> "$CALL_LOG"
[[ "$1" != run || "$*" != *ubuntu:24.04* || "${@: -1}" != fresh ]]
''')
    docker.chmod(0o755)
    monkeypatch.setenv("CALL_LOG", str(log))
    monkeypatch.setenv("PATH", f"{fake_bin}:/usr/bin:/bin")
    candidate, baseline = tmp_path / "candidate.zip", tmp_path / "previous.zip"
    candidate.touch()
    baseline.touch()
    result = subprocess.run(["bash", str(ROOT / "scripts/test_release_installation.sh"), str(candidate), str(baseline), str(tmp_path / "reports")], capture_output=True, text=True)
    assert result.returncode == 1
    calls = [line for line in log.read_text().splitlines() if line.startswith("run ")]
    assert len(calls) == 6
    assert sum(line.endswith(" fresh") for line in calls) == 3
    assert sum(line.endswith(" upgrade") for line in calls) == 3
    assert all("--rm --init" in line and "/workspace:ro" in line for line in calls)
    assert "archlinux:latest upgrade passed" in result.stdout
