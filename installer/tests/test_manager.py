from __future__ import annotations

import hashlib
import http.server
import json
import os
import fcntl
import pty
import select
import shutil
import subprocess
import sys
import tarfile
import termios
import threading
import zipfile
from pathlib import Path

import pytest

from opencrow_manager import (
    InstallError,
    Paths,
    StateEngine,
    deep_merge,
    parse_semver,
    remove_opencrow_hooks,
    version_is_supported,
)


REPOSITORY = Path(__file__).resolve().parents[2]


def paths_for(tmp_path: Path) -> Paths:
    home = tmp_path / "home"
    return Paths(home=home, data=home / ".local/share/opencrow", state=home / ".local/state/opencrow", bin=home / ".local/bin")


def test_skills_install_is_rootless_and_omits_heavy_surface(tmp_path: Path) -> None:
    paths = paths_for(tmp_path)
    engine = StateEngine(paths)
    state = engine.install(source=REPOSITORY, mode="skills", agents=["codex", "opencode"])
    assert state["install_mode"] == "skills"
    assert (paths.bin / "opencrow").is_file()
    assert (paths.bin / "opencrow-lifecycle-mcp").is_file()
    assert not (paths.bin / "opencrow-init").exists()
    assert not (paths.current / "services/constellation").exists()
    assert not (paths.current / "packages/mcp").exists()
    assert (paths.home / ".codex/skills/netcat-async").is_symlink()
    assert (paths.home / ".config/opencode/plugins/opencrow-lifecycle.js").is_file()


def test_full_install_upgrades_in_place_and_retains_one_snapshot(tmp_path: Path) -> None:
    paths = paths_for(tmp_path)
    engine = StateEngine(paths)
    engine.install(source=REPOSITORY, mode="skills", agents=["codex"])
    first_manifest = paths.manifest.read_text()
    state = engine.install(source=REPOSITORY, mode="full", agents=["codex"], toolboxes=["crypto", "utility"])
    assert state["install_mode"] == "full"
    assert paths.previous.is_dir()
    assert json.loads(paths.previous_manifest.read_text())["install_mode"] == "skills"
    assert (paths.bin / "opencrow-init").is_file()
    assert (paths.bin / "opencrow-crypto-mcp").is_file()
    assert (paths.current / "services/constellation").is_dir()
    rolled_back = engine.rollback()
    assert rolled_back["install_mode"] == "skills"
    assert paths.manifest.read_text() == first_manifest


def test_conflicting_config_is_backed_up_and_non_opencrow_hooks_survive(tmp_path: Path) -> None:
    paths = paths_for(tmp_path)
    hooks = paths.home / ".codex/hooks.json"
    hooks.parent.mkdir(parents=True)
    hooks.write_text(
        json.dumps(
            {
                "hooks": {
                    "Stop": [
                        {"hooks": [{"type": "command", "command": "my-check"}]},
                        {"hooks": [{"type": "command", "command": "opencrow-lifecycle-hook stale"}]},
                    ]
                }
            }
        )
    )
    engine = StateEngine(paths)
    state = engine.install(source=REPOSITORY, mode="skills", agents=["codex"])
    merged = json.loads(hooks.read_text())
    encoded = json.dumps(merged)
    assert "my-check" in encoded
    assert "opencrow-lifecycle-hook stop --provider codex" in encoded
    assert "opencrow-lifecycle-hook stale" not in encoded
    assert state["config_backups"]
    assert Path(state["config_backups"][0]["backup"]).is_file()


def test_repair_and_uninstall_touch_only_managed_files(tmp_path: Path) -> None:
    paths = paths_for(tmp_path)
    unrelated = paths.home / ".codex/unrelated.txt"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text("keep")
    engine = StateEngine(paths)
    engine.install(source=REPOSITORY, mode="full", agents=["codex"], toolboxes=["crypto"])
    skill = paths.home / ".codex/skills/netcat-async"
    skill.unlink()
    engine.repair()
    assert skill.is_symlink()
    assert (paths.bin / "opencrow-crypto-mcp").exists()
    result = engine.uninstall(purge_env=False, purge_system=False, purge_agent_clis=False)
    assert result["ok"]
    assert unrelated.read_text() == "keep"
    assert not paths.manifest.exists()
    assert not (paths.bin / "opencrow-crypto-mcp").exists()
    assert "OpenCROW PATH" not in (paths.home / ".bashrc").read_text()


def test_deselecting_provider_and_toolbox_removes_only_managed_entries(tmp_path: Path) -> None:
    paths = paths_for(tmp_path)
    engine = StateEngine(paths)
    engine.install(source=REPOSITORY, mode="full", agents=["codex", "claude"], toolboxes=["crypto"])
    claude_config = paths.home / ".claude/settings.json"
    value = json.loads(claude_config.read_text())
    value["userSetting"] = "keep"
    claude_config.write_text(json.dumps(value))
    engine.install(source=REPOSITORY, mode="full", agents=["codex"], toolboxes=["utility"])
    assert not (paths.bin / "opencrow-crypto-mcp").exists()
    assert (paths.bin / "opencrow-utility-mcp").exists()
    assert not (paths.home / ".claude/skills/netcat-async").exists()
    cleaned = json.loads(claude_config.read_text())
    assert cleaned["userSetting"] == "keep"
    assert "opencrow-lifecycle-hook" not in json.dumps(cleaned)


def test_invalid_provider_config_fails_before_managed_snapshot_changes(tmp_path: Path) -> None:
    paths = paths_for(tmp_path)
    engine = StateEngine(paths)
    engine.install(source=REPOSITORY, mode="skills", agents=["codex"])
    original_hashes = dict(engine.state()["managed_hashes"])
    config = paths.home / ".claude/settings.json"
    config.parent.mkdir(parents=True)
    config.write_text("not json")
    with pytest.raises((InstallError, json.JSONDecodeError)):
        engine.install(source=REPOSITORY, mode="full", agents=["codex", "claude"])
    assert engine.state()["managed_hashes"] == original_hashes
    assert engine.doctor()["ok"] is True


def test_legacy_install_state_is_rejected_instead_of_migrated(tmp_path: Path) -> None:
    paths = paths_for(tmp_path)
    paths.manifest.parent.mkdir(parents=True)
    paths.manifest.write_text('{"schema_version":1,"legacy_session":"unmigrated"}\n')
    with pytest.raises(InstallError, match="not migrated"):
        StateEngine(paths).install(source=REPOSITORY, mode="skills", agents=["codex"])


def test_full_install_cannot_be_downgraded_by_skills_product(tmp_path: Path) -> None:
    paths = paths_for(tmp_path)
    engine = StateEngine(paths)
    engine.install(source=REPOSITORY, mode="full", agents=["codex"], toolboxes=["utility"])
    with pytest.raises(InstallError, match="cannot be downgraded"):
        engine.install(source=REPOSITORY, mode="skills", agents=["codex"])
    assert engine.state()["install_mode"] == "full"


def test_external_package_purge_ledger_survives_deselection(tmp_path: Path) -> None:
    paths = paths_for(tmp_path)
    engine = StateEngine(paths)
    engine.install(
        source=REPOSITORY,
        mode="full",
        agents=["codex"],
        toolboxes=["crypto"],
        package_methods={
            "os_packages": {
                "method": "apt",
                "resolved": ["hashcat"],
                "installed_by_opencrow": ["hashcat"],
                "preexisting": [],
                "unresolved": [],
            }
        },
    )
    state = engine.install(
        source=REPOSITORY,
        mode="full",
        agents=["codex"],
        toolboxes=["utility"],
        package_methods={
            "os_packages": {
                "method": "apt",
                "resolved": ["jq"],
                "installed_by_opencrow": ["jq"],
                "preexisting": [],
                "unresolved": [],
            }
        },
    )
    assert state["selected_toolboxes"] == ["utility"]
    assert state["package_methods"]["os_packages"]["installed_by_opencrow"] == ["hashcat", "jq"]


@pytest.mark.parametrize(
    ("provider", "relative"),
    [
        ("claude", ".local/share/claude"),
        ("antigravity", ".local/bin/agy"),
    ],
)
def test_receipt_owned_vendor_cli_paths_are_purgeable(
    tmp_path: Path, provider: str, relative: str
) -> None:
    paths = paths_for(tmp_path)
    target = paths.home / relative
    if target.suffix or target.name == "agy":
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("provider binary")
    else:
        target.mkdir(parents=True)
        (target / "version").write_text("installed")
    state = {
        "package_methods": {
            "agent_clis": {
                "installed": [provider],
                "receipts": {provider: {"owned_paths": [{"path": str(target)}]}},
            }
        }
    }
    removed, unresolved = StateEngine(paths)._purge_agent_clis(state)
    assert removed == [provider]
    assert unresolved == []
    assert not target.exists()


def test_claude_receipt_purge_preserves_configuration(tmp_path: Path) -> None:
    paths = paths_for(tmp_path)
    install_root = paths.home / ".local/share/claude"
    install_root.mkdir(parents=True)
    (install_root / "version").write_text("2.1.0")
    configuration = paths.home / ".claude/settings.json"
    configuration.parent.mkdir(parents=True)
    configuration.write_text('{"theme":"dark"}\n')
    state = {
        "package_methods": {
            "agent_clis": {
                "installed": ["claude"],
                "receipts": {"claude": {"owned_paths": [{"path": str(install_root)}]}},
            }
        }
    }
    removed, unresolved = StateEngine(paths)._purge_agent_clis(state)
    assert removed == ["claude"] and unresolved == []
    assert not install_root.exists()
    assert configuration.read_text() == '{"theme":"dark"}\n'


def test_agent_cli_receipt_helper_detects_new_claude_install_root(tmp_path: Path) -> None:
    helper = REPOSITORY / "installer/lib/agent_cli_receipts.py"
    home = tmp_path / "home"
    home.mkdir()
    before = subprocess.check_output(
        [sys.executable, str(helper), "snapshot", "--home", str(home), "--providers", "claude"],
        text=True,
    ).strip()
    install_root = home / ".local/share/claude"
    install_root.mkdir(parents=True)
    (install_root / "version").write_text("2.1.0")
    value = json.loads(
        subprocess.check_output(
            [
                sys.executable,
                str(helper),
                "receipts",
                "--home",
                str(home),
                "--providers",
                "claude",
                "--before",
                before,
            ],
            text=True,
        )
    )
    assert str(install_root) in {item["path"] for item in value["claude"]["owned_paths"]}


def test_agent_cli_receipt_helper_detects_new_antigravity_binary(tmp_path: Path) -> None:
    helper = REPOSITORY / "installer/lib/agent_cli_receipts.py"
    home = tmp_path / "home"
    home.mkdir()
    before = subprocess.check_output(
        [sys.executable, str(helper), "snapshot", "--home", str(home), "--providers", "antigravity"],
        text=True,
    ).strip()
    binary = home / ".local/bin/agy"
    binary.parent.mkdir(parents=True)
    binary.write_text("agy")
    value = json.loads(
        subprocess.check_output(
            [
                sys.executable,
                str(helper),
                "receipts",
                "--home",
                str(home),
                "--providers",
                "antigravity",
                "--before",
                before,
            ],
            text=True,
        )
    )
    assert str(binary) in {item["path"] for item in value["antigravity"]["owned_paths"]}


def test_antigravity_receipt_outside_target_home_is_preserved(tmp_path: Path) -> None:
    paths = paths_for(tmp_path)
    outside = tmp_path / "shared/agy"
    outside.parent.mkdir(parents=True)
    outside.write_text("user owned")
    state = {
        "package_methods": {
            "agent_clis": {
                "installed": ["antigravity"],
                "receipts": {"antigravity": {"owned_paths": [{"path": str(outside)}]}},
            }
        }
    }
    removed, unresolved = StateEngine(paths)._purge_agent_clis(state)
    assert removed == []
    assert "unsafe receipt path" in unresolved[0]
    assert outside.read_text() == "user owned"


def test_vendor_cli_purge_without_receipt_is_unresolved(tmp_path: Path) -> None:
    paths = paths_for(tmp_path)
    state = {"package_methods": {"agent_clis": {"installed": ["claude"]}}}
    removed, unresolved = StateEngine(paths)._purge_agent_clis(state)
    assert removed == []
    assert "ownership receipt" in unresolved[0]


def test_codex_cli_purge_uses_recorded_npm_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = paths_for(tmp_path)
    commands: list[list[str]] = []
    monkeypatch.setattr("opencrow_manager.shutil.which", lambda command: f"/usr/bin/{command}")

    def run(command, **_kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("opencrow_manager.subprocess.run", run)
    state = {"package_methods": {"agent_clis": {"installed": ["codex"]}}}
    removed, unresolved = StateEngine(paths)._purge_agent_clis(state)
    assert removed == ["codex"] and unresolved == []
    assert commands == [
        ["npm", "uninstall", "--global", "--prefix", str(paths.home / ".local"), "@openai/codex"]
    ]


def test_opencode_cli_purge_uses_native_keep_data_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = paths_for(tmp_path)
    commands: list[list[str]] = []
    monkeypatch.setattr("opencrow_manager.shutil.which", lambda command: f"/usr/bin/{command}")

    def run(command, **_kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("opencrow_manager.subprocess.run", run)
    state = {"package_methods": {"agent_clis": {"installed": ["opencode"]}}}
    removed, unresolved = StateEngine(paths)._purge_agent_clis(state)
    assert removed == ["opencode"] and unresolved == []
    assert commands == [["opencode", "uninstall", "--force", "--keep-config", "--keep-data"]]


def test_opencode_v2_config_shape_is_selected_from_detected_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = paths_for(tmp_path)
    monkeypatch.setattr("opencrow_manager.command_version", lambda _command: "opencode 2.1.0")
    StateEngine(paths).install(source=REPOSITORY, mode="skills", agents=["opencode"])
    config = json.loads((paths.home / ".config/opencode/opencode.json").read_text())
    assert "opencrow-lifecycle" in config["mcp"]["servers"]


def test_agent_cli_receipts_survive_desired_state_merge() -> None:
    from opencrow_manager import merge_package_history

    previous = {
        "agent_clis": {
            "installed": ["claude"],
            "receipts": {"claude": {"owned_paths": [{"path": "/safe/claude"}]}},
        }
    }
    incoming = {
        "agent_clis": {
            "installed": ["antigravity"],
            "receipts": {"antigravity": {"owned_paths": [{"path": "/safe/agy"}]}},
        }
    }
    merged = merge_package_history(previous, incoming)
    assert merged["agent_clis"]["installed"] == ["claude", "antigravity"]
    assert set(merged["agent_clis"]["receipts"]) == {"claude", "antigravity"}


@pytest.mark.skipif(sys.platform != "linux", reason="installer supports Linux PTYs")
def test_interactive_back_returns_to_immediately_previous_screen(tmp_path: Path) -> None:
    master, slave = pty.openpty()

    def controlling_terminal() -> None:
        os.setsid()
        fcntl.ioctl(slave, termios.TIOCSCTTY, 0)

    environment = {**os.environ, "PATH": "/usr/bin:/bin", "TERM": "xterm"}
    process = subprocess.Popen(
        ["/bin/bash", str(REPOSITORY / "installer/install.sh"), "--dry-run"],
        cwd=REPOSITORY,
        env=environment,
        stdin=slave,
        stdout=slave,
        stderr=slave,
        preexec_fn=controlling_terminal,
        close_fds=True,
    )
    os.close(slave)
    output = bytearray()

    def read_until(marker: bytes, timeout: float = 8.0) -> None:
        import time

        deadline = time.monotonic() + timeout
        while marker not in output and time.monotonic() < deadline:
            ready, _, _ = select.select([master], [], [], 0.2)
            if ready:
                try:
                    output.extend(os.read(master, 65536))
                except OSError:
                    break
        assert marker in output, output.decode(errors="replace")

    try:
        read_until(b"1/6 Agent integrations")
        os.write(master, b" \r")  # select Codex, then confirm
        read_until(b"2/6 Optionally install selected missing agent CLIs")
        os.write(master, b"\r")  # leave optional CLI install unchecked
        read_until(b"3/6 Miniconda")
        agent_screen_count = output.count(b"1/6 Agent integrations")
        os.write(master, b"b")
        first = output.count(b"2/6 Optionally install selected missing agent CLIs")
        import time

        deadline = time.monotonic() + 5
        while output.count(b"2/6 Optionally install selected missing agent CLIs") == first and time.monotonic() < deadline:
            ready, _, _ = select.select([master], [], [], 0.2)
            if ready:
                output.extend(os.read(master, 65536))
        assert output.count(b"2/6 Optionally install selected missing agent CLIs") >= 2
        assert output.count(b"1/6 Agent integrations") == agent_screen_count
        os.write(master, b"q")
        assert process.wait(timeout=5) == 1
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        os.close(master)


def test_list_merge_is_additive_only_for_hook_groups() -> None:
    assert deep_merge(["old"], ["new"]) == ["new"]
    old = [{"hooks": [{"command": "mine"}]}]
    new = [{"hooks": [{"command": "opencrow-lifecycle-hook stop"}]}]
    assert deep_merge(old, new) == old + new
    assert remove_opencrow_hooks(old + new) == old


def test_managed_ctf_environment_is_created_under_opencrow_data(tmp_path: Path) -> None:
    fake_conda = tmp_path / "conda"
    fake_conda.write_text(
        "#!/bin/sh\n"
        "while [ \"$#\" -gt 0 ]; do\n"
        "  if [ \"$1\" = --prefix ]; then shift; prefix=$1; fi\n"
        "  shift\n"
        "done\n"
        "mkdir -p \"$prefix/bin\"\n"
        "printf '#!/bin/sh\\nexit 0\\n' >\"$prefix/bin/python\"\n"
        "chmod +x \"$prefix/bin/python\"\n"
    )
    fake_conda.chmod(0o755)
    script = REPOSITORY / "installer/lib/install_python_envs.py"
    manifest = REPOSITORY / "installer/manifests/python-environments.json"
    data_root = tmp_path / "data"
    process = subprocess.run(
        [
            sys.executable,
            str(script),
            "--conda",
            str(fake_conda),
            "--manifest",
            str(manifest),
            "--data-root",
            str(data_root),
            "--toolboxes",
            "utility",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONNOUSERSITE": "1"},
    )
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout)["installed"] == ["ctf"]
    assert (data_root / "envs/ctf/bin/python").is_file()


def test_remote_latest_update_verifies_release_and_embedded_checksums(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    web_root = tmp_path / "web"
    release_root = web_root / "releases/latest/download"
    release_root.mkdir(parents=True)
    stage = tmp_path / "stage"
    (stage / "packages/lifecycle").mkdir(parents=True)
    (stage / "installer").mkdir()
    managed = stage / "installer/opencrow_manager.py"
    managed.write_text("# fixture\n")
    manifest = stage / "release-manifest.json"
    manifest.write_text('{"schema_version":2,"version":"2.0.0"}\n')
    embedded = {
        "installer/opencrow_manager.py": hashlib.sha256(managed.read_bytes()).hexdigest(),
        "release-manifest.json": hashlib.sha256(manifest.read_bytes()).hexdigest(),
    }
    (stage / "checksums.json").write_text(json.dumps(embedded))
    bundle = release_root / "opencrow-full.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        for path in stage.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(stage))
    (release_root / "release-checksums.txt").write_text(
        f"{hashlib.sha256(bundle.read_bytes()).hexdigest()}  opencrow-full.zip\n"
    )

    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            pass

    handler = lambda *args, **kwargs: QuietHandler(*args, directory=str(web_root), **kwargs)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv(
        "OPENCROW_RELEASE_BASE_URL", f"http://127.0.0.1:{server.server_port}/releases/download"
    )
    extracted: Path | None = None
    try:
        extracted = StateEngine(paths_for(tmp_path / "install"))._download_release_source(None)
        assert (extracted / "installer/opencrow_manager.py").read_text() == "# fixture\n"
    finally:
        server.shutdown()
        server.server_close()
        if extracted:
            shutil.rmtree(extracted)


def _fake_provider(path: Path, name: str = "codex") -> None:
    target = path / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"#!/bin/sh\necho '{name} 99.0.0'\n")
    target.chmod(0o755)


@pytest.mark.parametrize(
    ("detected", "minimum", "expected"),
    [
        ("codex 0.115.9", "0.116.0", False),
        ("codex 0.116.0", "0.116.0", True),
        ("codex 0.117.0", "0.116.0", True),
        ("codex 0.116.0-rc.1", "0.116.0", False),
        ("installed (version unavailable)", "0.116.0", None),
    ],
)
def test_provider_semver_policy(detected: str, minimum: str, expected: bool | None) -> None:
    assert version_is_supported(detected, minimum) is expected
    if expected is not None:
        assert parse_semver(detected) is not None


def test_known_incompatible_provider_is_rejected_before_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = paths_for(tmp_path)
    engine = StateEngine(paths)
    monkeypatch.setattr("opencrow_manager.command_version", lambda _command: "codex 0.115.0")
    with pytest.raises(InstallError, match="before mutation"):
        engine.install(source=REPOSITORY, mode="skills", agents=["codex"])
    assert not paths.current.exists()
    assert not paths.manifest.exists()


def test_unknown_provider_version_installs_with_prominent_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = paths_for(tmp_path)
    engine = StateEngine(paths)
    monkeypatch.setattr("opencrow_manager.command_version", lambda _command: "development build")
    state = engine.install(source=REPOSITORY, mode="skills", agents=["codex"])
    compatibility = state["provider_compatibility"]["codex"]
    assert compatibility["compatibility"] == "unknown"
    assert compatibility["warning"]


def test_skills_shell_uses_rootless_system_venv_without_conda(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    _fake_provider(fake_bin)
    home = tmp_path / "home"
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "OPENCROW_TARGET_HOME": str(home),
        "OPENCROW_BIN_DIR": str(home / ".local/bin"),
        "XDG_DATA_HOME": str(home / ".local/share"),
        "XDG_STATE_HOME": str(home / ".local/state"),
    }
    environment.pop("OPENCROW_PYTHON", None)
    process = subprocess.run(
        ["bash", str(REPOSITORY / "installer/skills.sh"), "--yes"],
        cwd=REPOSITORY,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    assert (home / ".local/share/opencrow/helper/bin/python").is_file()
    assert not (home / ".local/share/opencrow/miniconda").exists()
    assert not (home / ".local/bin/opencrow-init").exists()


@pytest.mark.parametrize(
    ("machine", "asset_name"),
    (
        ("x86_64", "opencrow-python-linux-x86_64.tar.gz"),
        ("aarch64", "opencrow-python-linux-arm64.tar.gz"),
    ),
)
def test_skills_shell_uses_verified_portable_python_when_venv_fails(
    tmp_path: Path, machine: str, asset_name: str
) -> None:
    fake_bin = tmp_path / "bin"
    _fake_provider(fake_bin)
    fake_python = fake_bin / "python3"
    fake_python.write_text(
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = -m ] && [ \"${2:-}\" = venv ]; then exit 1; fi\n"
        f"exec {sys.executable} \"$@\"\n"
    )
    fake_python.chmod(0o755)
    asset_root = tmp_path / "portable-root/opencrow-python"
    (asset_root / "bin").mkdir(parents=True)
    os.symlink(sys.executable, asset_root / "bin/python")
    archive = tmp_path / "portable-python.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(asset_root, arcname=asset_root.name)
    checksums = tmp_path / "release-checksums.txt"
    checksums.write_text(
        f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {asset_name}\n"
    )
    home = tmp_path / "home"
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "OPENCROW_TEST_MACHINE": machine,
        "OPENCROW_TARGET_HOME": str(home),
        "OPENCROW_BIN_DIR": str(home / ".local/bin"),
        "XDG_DATA_HOME": str(home / ".local/share"),
        "XDG_STATE_HOME": str(home / ".local/state"),
        "OPENCROW_PORTABLE_PYTHON_URL": archive.as_uri(),
        "OPENCROW_PORTABLE_PYTHON_CHECKSUMS_URL": checksums.as_uri(),
    }
    environment.pop("OPENCROW_PYTHON", None)
    process = subprocess.run(
        ["bash", str(REPOSITORY / "installer/skills.sh"), "--agents", "codex", "--yes"],
        cwd=REPOSITORY,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    helper = home / ".local/share/opencrow/helper/bin/python"
    assert helper.is_symlink()
    assert (home / ".local/bin/opencrow").is_file()
