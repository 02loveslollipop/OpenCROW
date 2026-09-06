#!/usr/bin/env python3
"""Transactional installer and management command for OpenCROW v2.

The module is standard-library-only so the skills package can run in a tiny
helper environment.  Provider configuration is merged conservatively and every
affected file is backed up before the OpenCROW-owned entry is replaced.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


VERSION = "2.1.2"
PROVIDERS = ("codex", "opencode", "claude", "antigravity")
COMMANDS = {"codex": "codex", "opencode": "opencode", "claude": "claude", "antigravity": "agy"}
SKILLS_DIRS = {
    "codex": ".codex/skills",
    "opencode": ".config/opencode/skills",
    "claude": ".claude/skills",
    "antigravity": ".agents/skills",
}
JSON_CONFIGS = {
    "opencode": (".config/opencode/opencode.json", "integrations/opencode/config.fragment.json"),
    "claude": (".claude/settings.json", "integrations/claude/settings.fragment.json"),
    "antigravity": (".gemini/antigravity-cli/settings.json", "integrations/antigravity/settings.fragment.json"),
}
MANAGED_TOML_START = "# >>> OpenCROW managed integration >>>"
MANAGED_TOML_END = "# <<< OpenCROW managed integration <<<"


class InstallError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def atomic_text(path: Path, value: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing_mode = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        existing_mode = mode
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, existing_mode)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_hashes(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not root.exists():
        return result
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            result[path.relative_to(root).as_posix()] = sha256_file(path)
    return result


def copy_tree(source: Path, target: Path) -> None:
    if not source.is_dir():
        raise InstallError(f"Required source directory is missing: {source}")
    shutil.copytree(
        source,
        target,
        dirs_exist_ok=True,
        symlinks=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".pytest_cache"),
    )


def command_version(command: str) -> str | None:
    executable = shutil.which(command)
    if not executable:
        return None
    for arguments in ([executable, "--version"], [executable, "version"]):
        try:
            result = subprocess.run(arguments, capture_output=True, text=True, timeout=5, check=False)
        except (OSError, subprocess.SubprocessError):
            continue
        output = (result.stdout or result.stderr).strip().splitlines()
        if output:
            return output[0][:200]
    return "installed (version unavailable)"


def parse_semver(value: str | None) -> tuple[int, int, int, str | None] | None:
    """Extract a conservative SemVer value from vendor CLI output."""

    if not value:
        return None
    match = re.search(r"(?<!\d)v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?", value)
    if not match:
        return None
    return int(match[1]), int(match[2]), int(match[3]), match[4]


def version_is_supported(detected: str, minimum: str) -> bool | None:
    actual = parse_semver(detected)
    required = parse_semver(minimum)
    if actual is None or required is None:
        return None
    if actual[:3] != required[:3]:
        return actual[:3] > required[:3]
    if actual[3] and not required[3]:
        return False
    return True


def load_integration_manifest(root: Path) -> dict[str, Any]:
    path = root / "integrations" / "manifest.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InstallError(f"Cannot read provider compatibility manifest {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 2:
        raise InstallError(f"Invalid provider compatibility manifest: {path}")
    return value


def deep_merge(existing: Any, incoming: Any) -> Any:
    if isinstance(existing, dict) and isinstance(incoming, dict):
        result = dict(existing)
        for key, value in incoming.items():
            result[key] = deep_merge(result.get(key), value) if key in result else value
        return result
    if isinstance(existing, list) and isinstance(incoming, list):
        # Hook matcher groups are additive; scalar command/argument arrays are
        # authoritative replacements for the same named integration.
        if any(isinstance(item, dict) and "hooks" in item for item in incoming):
            return [*existing, *incoming]
        return incoming
    return incoming


def remove_opencrow_hooks(value: Any) -> Any:
    if isinstance(value, list):
        kept = []
        for item in value:
            encoded = json.dumps(item, sort_keys=True)
            if "opencrow-lifecycle-hook" not in encoded:
                kept.append(remove_opencrow_hooks(item))
        return kept
    if isinstance(value, dict):
        return {key: remove_opencrow_hooks(item) for key, item in value.items()}
    return value


def merge_package_history(previous: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Retain explicitly purgeable external installs across desired-state changes."""

    if not previous:
        return incoming
    if not incoming:
        return previous
    result = json.loads(json.dumps(previous))
    for section, values in incoming.items():
        if not isinstance(values, dict):
            result[section] = values
            continue
        existing = result.get(section) if isinstance(result.get(section), dict) else {}
        merged = {**existing, **values}
        for key in ("resolved", "installed_by_opencrow", "preexisting", "installed"):
            old_items = existing.get(key, []) if isinstance(existing.get(key), list) else []
            new_items = values.get(key, []) if isinstance(values.get(key), list) else []
            if old_items or new_items:
                merged[key] = list(dict.fromkeys([*old_items, *new_items]))
        if "unresolved" in existing or "unresolved" in values:
            new_unresolved = values.get("unresolved", []) if isinstance(values.get("unresolved"), list) else []
            resolved = set(merged.get("resolved", [])) | set(merged.get("installed", []))
            merged["unresolved"] = [item for item in dict.fromkeys(new_unresolved) if item not in resolved]
        if section == "agent_clis":
            old_receipts = existing.get("receipts", {}) if isinstance(existing.get("receipts"), dict) else {}
            new_receipts = values.get("receipts", {}) if isinstance(values.get("receipts"), dict) else {}
            merged["receipts"] = {**old_receipts, **new_receipts}
        if section == "miniconda":
            merged["installed"] = bool(existing.get("installed")) or bool(values.get("installed"))
        result[section] = merged
    return result


@dataclass(frozen=True)
class Paths:
    home: Path
    data: Path
    state: Path
    bin: Path

    @classmethod
    def resolve(cls) -> "Paths":
        home = Path(os.environ.get("OPENCROW_TARGET_HOME", str(Path.home()))).expanduser().resolve()
        data_base = Path(os.environ.get("XDG_DATA_HOME", str(home / ".local" / "share")))
        state_base = Path(os.environ.get("XDG_STATE_HOME", str(home / ".local" / "state")))
        bin_dir = Path(os.environ.get("OPENCROW_BIN_DIR", str(home / ".local" / "bin")))
        return cls(home=home, data=data_base / "opencrow", state=state_base / "opencrow", bin=bin_dir)

    @property
    def current(self) -> Path:
        return self.data / "current"

    @property
    def previous(self) -> Path:
        return self.data / "previous"

    @property
    def manifest(self) -> Path:
        return self.state / "state.json"

    @property
    def previous_manifest(self) -> Path:
        return self.state / "previous-state.json"

    @property
    def backups(self) -> Path:
        return self.state / "backups"


class StateEngine:
    def __init__(self, paths: Paths | None = None) -> None:
        self.paths = paths or Paths.resolve()

    def state(self) -> dict[str, Any]:
        if not self.paths.manifest.exists():
            return {}
        try:
            value = json.loads(self.paths.manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise InstallError(f"Invalid desired-state manifest: {exc}") from exc
        if not isinstance(value, dict):
            raise InstallError("Desired-state manifest must be a JSON object.")
        if value.get("schema_version") != 2:
            raise InstallError(
                "Legacy OpenCROW install state is not migrated by v2; remove the prior installation state before installing."
            )
        return value

    def provider_compatibility(self, agents: Iterable[str], *, root: Path | None = None) -> dict[str, Any]:
        manifest_root = root or self.paths.current
        providers = load_integration_manifest(manifest_root).get("providers", {})
        result: dict[str, Any] = {}
        for provider in agents:
            specification = providers.get(provider, {}) if isinstance(providers, dict) else {}
            minimum = str(specification.get("minimum_version") or "")
            version = command_version(COMMANDS[provider])
            supported = version_is_supported(version or "", minimum)
            if supported is True:
                compatibility = "compatible"
                warning = None
            elif supported is False:
                compatibility = "incompatible"
                warning = (
                    f"{provider} {version} is below the required minimum {minimum}; "
                    "update the provider CLI before installing or scheduling it."
                )
            else:
                compatibility = "unknown"
                warning = (
                    f"Could not verify {provider} against required minimum {minimum}: "
                    f"{version or 'command unavailable'}."
                )
            result[provider] = {
                "available": version is not None,
                "version": version,
                "minimum_version": minimum,
                "compatibility": compatibility,
                "warning": warning,
            }
        return result

    @staticmethod
    def _reject_incompatible(compatibility: dict[str, Any]) -> None:
        failures = [
            str(value.get("warning"))
            for value in compatibility.values()
            if isinstance(value, dict) and value.get("compatibility") == "incompatible"
        ]
        if failures:
            raise InstallError("Provider compatibility preflight failed before mutation: " + "; ".join(failures))

    def _write_state(self, value: dict[str, Any], *, previous: dict[str, Any] | None = None) -> None:
        self.paths.state.mkdir(parents=True, exist_ok=True)
        if previous:
            atomic_text(self.paths.previous_manifest, json.dumps(previous, indent=2, sort_keys=True) + "\n")
        atomic_text(self.paths.manifest, json.dumps(value, indent=2, sort_keys=True) + "\n")

    def _backup(self, path: Path, backups: list[dict[str, Any]]) -> None:
        if not path.exists() or path.is_dir():
            return
        relative = path.relative_to(self.paths.home).as_posix().replace("/", "__")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        destination = self.paths.backups / f"{stamp}-{relative}"
        counter = 1
        while destination.exists():
            destination = self.paths.backups / f"{stamp}-{counter}-{relative}"
            counter += 1
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        backups.append({"path": str(path), "backup": str(destination), "sha256": sha256_file(destination)})

    def _stage(self, source: Path, mode: str) -> Path:
        self.paths.data.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=".stage-", dir=self.paths.data))
        try:
            copy_tree(source / "packages" / "lifecycle", stage / "packages" / "lifecycle")
            copy_tree(source / "skills", stage / "skills")
            copy_tree(source / "integrations", stage / "integrations")
            (stage / "installer").mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / "installer" / "opencrow_manager.py", stage / "installer" / "opencrow_manager.py")
            if mode == "full":
                if (source / "packages" / "mcp").is_dir():
                    copy_tree(source / "packages" / "mcp", stage / "packages" / "mcp")
                if (source / "services" / "constellation").is_dir():
                    copy_tree(source / "services" / "constellation", stage / "services" / "constellation")
            manifest = {
                "schema_version": 2,
                "version": VERSION,
                "mode": mode,
                "built_at": utc_now(),
            }
            atomic_text(stage / "release-manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
            hashes = tree_hashes(stage)
            atomic_text(stage / "checksums.json", json.dumps(hashes, indent=2, sort_keys=True) + "\n")
            return stage
        except Exception:
            shutil.rmtree(stage, ignore_errors=True)
            raise

    def _commit_stage(self, stage: Path) -> None:
        previous = self.paths.previous
        current = self.paths.current
        moved_previous = False
        if previous.exists():
            # Only retire the previous snapshot after the new stage is safely in place.
            os.replace(previous, previous.with_suffix(".retiring"))
            moved_previous = True
        moved_current = False
        try:
            if current.exists():
                os.replace(current, previous)
                moved_current = True
            os.replace(stage, current)
        except Exception:
            if not current.exists() and moved_current and previous.exists():
                os.replace(previous, current)
            if moved_previous:
                retiring = previous.with_suffix(".retiring")
                if retiring.exists() and not current.exists():
                    os.replace(retiring, previous)
            raise
        if moved_previous:
            shutil.rmtree(previous.with_suffix(".retiring"), ignore_errors=True)

    def _validate_stage(self, stage: Path, agents: list[str]) -> None:
        expected_path = stage / "checksums.json"
        manifest_path = stage / "release-manifest.json"
        expected = json.loads(expected_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(expected, dict) or manifest.get("schema_version") != 2:
            raise InstallError("Staged OpenCROW metadata is invalid.")
        for relative, digest in expected.items():
            path = stage / str(relative)
            if not path.is_file() or sha256_file(path) != digest:
                raise InstallError(f"Staged asset verification failed: {relative}")
        for provider in agents:
            if provider == "codex":
                json.loads((stage / "integrations/codex/hooks.json").read_text(encoding="utf-8"))
                existing = self.paths.home / ".codex/hooks.json"
            else:
                _relative, fragment = JSON_CONFIGS[provider]
                json.loads((stage / fragment).read_text(encoding="utf-8"))
                existing = self.paths.home / JSON_CONFIGS[provider][0]
            if existing.exists():
                value = json.loads(existing.read_text(encoding="utf-8"))
                if not isinstance(value, dict):
                    raise InstallError(f"Provider config is not a JSON object: {existing}")

    def _runtime_python_shell(self) -> str:
        helper = self.paths.data / "helper" / "bin" / "python"
        ctf = self.paths.data / "envs" / "ctf" / "bin" / "python"
        return (
            "export PYTHONDONTWRITEBYTECODE=1\n"
            'OPENCROW_RUNTIME_PYTHON="${OPENCROW_PYTHON:-}"\n'
            f'if [ ! -x "$OPENCROW_RUNTIME_PYTHON" ]; then OPENCROW_RUNTIME_PYTHON={shlex_quote(str(ctf))}; fi\n'
            f'if [ ! -x "$OPENCROW_RUNTIME_PYTHON" ]; then OPENCROW_RUNTIME_PYTHON={shlex_quote(str(helper))}; fi\n'
            'if [ ! -x "$OPENCROW_RUNTIME_PYTHON" ]; then OPENCROW_RUNTIME_PYTHON=$(command -v python3 || command -v python); fi\n'
        )

    def _write_launcher(self, name: str, module_or_path: str, managed: list[str]) -> None:
        target = self.paths.bin / name
        if module_or_path.startswith("module:"):
            module = module_or_path.split(":", 1)[1]
            lifecycle_root = self.paths.current / "packages" / "lifecycle"
            body = (
                "#!/bin/sh\nset -eu\n"
                f"export PYTHONPATH={shlex_quote(str(lifecycle_root))}${{PYTHONPATH:+:$PYTHONPATH}}\n"
                + self._runtime_python_shell()
                + f'exec "$OPENCROW_RUNTIME_PYTHON" -m {module} "$@"\n'
            )
        else:
            extra_path = ""
            if "/packages/mcp/" in module_or_path:
                core = self.paths.current / "packages" / "mcp" / "core"
                servers = self.paths.current / "packages" / "mcp" / "servers"
                extra_path = f"export PYTHONPATH={shlex_quote(str(core))}:{shlex_quote(str(servers))}${{PYTHONPATH:+:$PYTHONPATH}}\n"
            body = (
                "#!/bin/sh\nset -eu\n"
                + extra_path
                + self._runtime_python_shell()
                + f'exec "$OPENCROW_RUNTIME_PYTHON" {shlex_quote(module_or_path)} "$@"\n'
            )
        atomic_text(target, body, mode=0o755)
        os.chmod(target, 0o755)
        managed.append(str(target))

    def _write_constellation_launcher(self, name: str, module: str, managed: list[str]) -> None:
        target = self.paths.bin / name
        root = self.paths.current / "services" / "constellation"
        body = (
            "#!/bin/sh\nset -eu\n"
            f"export PYTHONPATH={shlex_quote(str(root))}${{PYTHONPATH:+:$PYTHONPATH}}\n"
            + self._runtime_python_shell()
            + f'exec "$OPENCROW_RUNTIME_PYTHON" -m constellation.{module} "$@"\n'
        )
        atomic_text(target, body, mode=0o755)
        os.chmod(target, 0o755)
        managed.append(str(target))

    def _write_rsx_launcher(self, managed: list[str]) -> None:
        target = self.paths.bin / "rsx"
        backend = self.paths.current / "skills" / "netcat-async" / "scripts" / "nc_async_session.py"
        body = (
            "#!/bin/sh\nset -eu\n"
            'case "${1:-}" in\n'
            "  listen|send|read|status|stop) ;;\n"
            "  *)\n"
            "    echo 'usage: rsx <listen|send|read|status|stop> [options]' >&2\n"
            "    echo 'rsx is listener-only and does not generate callback payloads.' >&2\n"
            "    exit 2\n"
            "    ;;\n"
            "esac\n"
            + self._runtime_python_shell()
            + f'exec "$OPENCROW_RUNTIME_PYTHON" {shlex_quote(str(backend))} "$@"\n'
        )
        atomic_text(target, body, mode=0o755)
        os.chmod(target, 0o755)
        managed.append(str(target))

    def _install_launchers(self, mode: str, toolboxes: list[str]) -> list[str]:
        self.paths.bin.mkdir(parents=True, exist_ok=True)
        managed: list[str] = []
        manager = self.paths.current / "installer" / "opencrow_manager.py"
        self._write_launcher("opencrow", str(manager), managed)
        self._write_launcher("opencrow-lifecycle-mcp", "module:opencrow_lifecycle.mcp_server", managed)
        self._write_launcher("opencrow-lifecycle-hook", "module:opencrow_lifecycle.hooks", managed)
        self._write_rsx_launcher(managed)
        if mode == "full":
            self._write_launcher("opencrow-init", "module:opencrow_lifecycle.init_cli", managed)
            server_names = {
                "utility": "utility",
                "network": "network",
                "reversing": "reversing",
                "pwn": "pwn",
                "web": "web",
                "forensics": "forensics",
                "stego": "stego",
                "crypto": "crypto",
                "osint": "osint",
            }
            servers = self.paths.current / "packages" / "mcp" / "servers"
            for toolbox in toolboxes:
                stem = server_names.get(toolbox)
                if stem:
                    self._write_launcher(f"opencrow-{stem}-mcp", str(servers / f"opencrow_{stem}_mcp.py"), managed)
            for stem in ("netcat", "ssh", "minecraft", "agy"):
                self._write_launcher(f"opencrow-{stem}-mcp", str(servers / f"opencrow_{stem}_mcp.py"), managed)
            self._write_constellation_launcher("opencrow-constellation-runtime", "runtime", managed)
            self._write_constellation_launcher("opencrow-constellation-backend", "backend", managed)
        else:
            legacy_init = self.paths.bin / "opencrow-init"
            if legacy_init.exists() and self._is_managed_launcher(legacy_init):
                legacy_init.unlink()
        return managed

    @staticmethod
    def _is_managed_launcher(path: Path) -> bool:
        try:
            return "opencrow" in path.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            return False

    def _install_skills(self, agents: list[str], backups: list[dict[str, Any]]) -> list[str]:
        managed: list[str] = []
        source = self.paths.current / "skills"
        skill_names = sorted(path.name for path in source.iterdir() if (path / "SKILL.md").is_file())
        previous_agents = self.state().get("selected_agents", [])
        for provider in set(previous_agents) - set(agents):
            self._remove_provider_skills(provider)
        for provider in agents:
            base = self.paths.home / SKILLS_DIRS[provider]
            base.mkdir(parents=True, exist_ok=True)
            for name in skill_names:
                destination = base / name
                desired = source / name
                if destination.is_symlink() and destination.resolve() == desired.resolve():
                    managed.append(str(destination))
                    continue
                if destination.exists() or destination.is_symlink():
                    self._backup_path(destination, backups)
                    if destination.is_dir() and not destination.is_symlink():
                        shutil.rmtree(destination)
                    else:
                        destination.unlink()
                destination.symlink_to(desired, target_is_directory=True)
                managed.append(str(destination))
        return managed

    def _backup_path(self, path: Path, backups: list[dict[str, Any]]) -> None:
        if path.is_symlink():
            backups.append({"path": str(path), "symlink": os.readlink(path)})
            return
        if path.is_dir():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            destination = self.paths.backups / f"{stamp}-{path.name}"
            counter = 1
            while destination.exists():
                destination = self.paths.backups / f"{stamp}-{counter}-{path.name}"
                counter += 1
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(path, destination)
            backups.append({"path": str(path), "backup": str(destination), "kind": "directory"})
        else:
            self._backup(path, backups)

    def _remove_provider_skills(self, provider: str) -> None:
        if provider not in SKILLS_DIRS:
            return
        base = self.paths.home / SKILLS_DIRS[provider]
        if not base.exists():
            return
        for path in base.iterdir():
            if path.is_symlink() and str(self.paths.data) in str(path.resolve(strict=False)):
                path.unlink()

    def _merge_json_config(self, provider: str, backups: list[dict[str, Any]]) -> list[str]:
        relative, fragment_relative = JSON_CONFIGS[provider]
        destination = self.paths.home / relative
        fragment_path = self.paths.current / fragment_relative
        existing: dict[str, Any] = {}
        if destination.exists():
            self._backup(destination, backups)
            try:
                loaded = json.loads(destination.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise InstallError(f"Cannot merge invalid provider config {destination}: {exc}") from exc
            if not isinstance(loaded, dict):
                raise InstallError(f"Provider config is not a JSON object: {destination}")
            existing = remove_opencrow_hooks(loaded)
        fragment = json.loads(fragment_path.read_text(encoding="utf-8"))
        if provider == "opencode":
            version = command_version("opencode") or ""
            major_match = re.search(r"\b(\d+)\.", version)
            if major_match and int(major_match.group(1)) >= 2:
                server = fragment.get("mcp", {}).get("opencrow-lifecycle")
                fragment["mcp"] = {"servers": {"opencrow-lifecycle": server}}
                legacy = existing.get("mcp")
                if isinstance(legacy, dict) and "opencrow-lifecycle" in legacy:
                    # Drop the pre-v2 server entry so the two layouts do not coexist.
                    del legacy["opencrow-lifecycle"]
        merged = deep_merge(existing, fragment)
        atomic_text(destination, json.dumps(merged, indent=2, sort_keys=True) + "\n")
        managed = [str(destination)]
        if provider == "opencode":
            plugin = self.paths.home / ".config/opencode/plugins/opencrow-lifecycle.js"
            plugin.parent.mkdir(parents=True, exist_ok=True)
            if plugin.exists():
                self._backup(plugin, backups)
            shutil.copy2(self.paths.current / "integrations/opencode/opencrow-lifecycle.js", plugin)
            managed.append(str(plugin))
        return managed

    def _merge_codex(self, backups: list[dict[str, Any]]) -> list[str]:
        config = self.paths.home / ".codex/config.toml"
        hooks = self.paths.home / ".codex/hooks.json"
        config.parent.mkdir(parents=True, exist_ok=True)
        if config.exists():
            self._backup(config, backups)
        text = config.read_text(encoding="utf-8") if config.exists() else ""
        pattern = re.compile(re.escape(MANAGED_TOML_START) + r".*?" + re.escape(MANAGED_TOML_END), re.DOTALL)
        text = pattern.sub("", text).rstrip()
        fragment = (self.paths.current / "integrations/codex/config.toml.fragment").read_text(encoding="utf-8").strip()
        features = re.search(
            r"^[ \t]*\[[ \t]*features[ \t]*\][ \t]*(?:#[^\n]*)?$"
            r"(?P<body>.*?)(?=^[ \t]*\[|\Z)",
            text,
            re.MULTILINE | re.DOTALL,
        )
        if features:
            if not re.search(r"^[ \t]*hooks[ \t]*=", features.group("body"), re.MULTILINE):
                insertion = features.start("body")
                text = text[:insertion] + "\nhooks = true" + text[insertion:]
            fragment = re.sub(r"\[\s*features\s*\]\s*\nhooks\s*=\s*true\s*", "", fragment).strip()
        atomic_text(config, text + ("\n\n" if text else "") + MANAGED_TOML_START + "\n" + fragment + "\n" + MANAGED_TOML_END + "\n")
        incoming = json.loads((self.paths.current / "integrations/codex/hooks.json").read_text(encoding="utf-8"))
        existing: dict[str, Any] = {}
        if hooks.exists():
            self._backup(hooks, backups)
            try:
                value = json.loads(hooks.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise InstallError(f"Cannot merge invalid Codex hooks {hooks}: {exc}") from exc
            existing = remove_opencrow_hooks(value if isinstance(value, dict) else {})
        merged = deep_merge(existing, incoming)
        atomic_text(hooks, json.dumps(merged, indent=2, sort_keys=True) + "\n")
        return [str(config), str(hooks)]

    def _merge_antigravity_mcp(self, backups: list[dict[str, Any]]) -> list[str]:
        destination = self.paths.home / ".gemini/antigravity-cli/mcp_config.json"
        existing: dict[str, Any] = {}
        if destination.exists():
            self._backup(destination, backups)
            try:
                loaded = json.loads(destination.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise InstallError(f"Cannot merge invalid Antigravity MCP config: {exc}") from exc
            if isinstance(loaded, dict):
                existing = loaded
        fragment = json.loads((self.paths.current / "integrations/antigravity/mcp_config.fragment.json").read_text())
        atomic_text(destination, json.dumps(deep_merge(existing, fragment), indent=2, sort_keys=True) + "\n")
        return [str(destination)]

    def _install_integrations(
        self,
        agents: list[str],
        backups: list[dict[str, Any]],
        compatibility: dict[str, Any] | None = None,
    ) -> tuple[list[str], dict[str, Any]]:
        managed: list[str] = []
        compatibility = compatibility or self.provider_compatibility(agents)
        for provider in agents:
            if provider == "codex":
                managed.extend(self._merge_codex(backups))
            else:
                managed.extend(self._merge_json_config(provider, backups))
                if provider == "antigravity":
                    managed.extend(self._merge_antigravity_mcp(backups))
        return managed, compatibility

    def _verify_installed_integrations(self, agents: list[str]) -> None:
        issues: list[str] = []
        for provider in agents:
            skill_dir = self.paths.home / SKILLS_DIRS[provider]
            if not any(skill_dir.glob("*/SKILL.md")):
                issues.append(f"{provider} skills were not discoverable")
            if provider == "codex":
                targets = (self.paths.home / ".codex/config.toml", self.paths.home / ".codex/hooks.json")
            elif provider == "antigravity":
                targets = (
                    self.paths.home / JSON_CONFIGS[provider][0],
                    self.paths.home / ".gemini/antigravity-cli/mcp_config.json",
                )
            else:
                targets = (self.paths.home / JSON_CONFIGS[provider][0],)
            for target in targets:
                try:
                    content = target.read_text(encoding="utf-8")
                except OSError:
                    issues.append(f"{provider} integration file is missing: {target}")
                    continue
                if "opencrow-lifecycle" not in content:
                    issues.append(f"{provider} lifecycle entry is missing from {target}")
        for launcher in ("opencrow", "opencrow-lifecycle-mcp", "opencrow-lifecycle-hook", "rsx"):
            if not os.access(self.paths.bin / launcher, os.X_OK):
                issues.append(f"managed launcher is not executable: {launcher}")
        if issues:
            raise InstallError("Integration verification failed: " + "; ".join(issues))

    def _configure_shells(self, backups: list[dict[str, Any]]) -> list[str]:
        managed: list[str] = []
        path_line = f'export PATH="{self.paths.bin}:$PATH"'
        start = "# >>> OpenCROW PATH >>>"
        end = "# <<< OpenCROW PATH <<<"
        for relative in (".bashrc", ".zshrc"):
            destination = self.paths.home / relative
            if destination.exists():
                self._backup(destination, backups)
            text = destination.read_text(encoding="utf-8") if destination.exists() else ""
            text = re.sub(re.escape(start) + r".*?" + re.escape(end), "", text, flags=re.DOTALL).rstrip()
            atomic_text(destination, text + ("\n\n" if text else "") + f"{start}\n{path_line}\n{end}\n")
            managed.append(str(destination))
        fish = self.paths.home / ".config/fish/conf.d/opencrow.fish"
        if fish.exists():
            self._backup(fish, backups)
        atomic_text(fish, f"fish_add_path {self.paths.bin}\n")
        managed.append(str(fish))
        return managed

    def install(
        self,
        *,
        source: Path,
        mode: str,
        agents: list[str],
        toolboxes: list[str] | None = None,
        tools: list[str] | None = None,
        package_methods: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if mode not in {"skills", "full"}:
            raise InstallError("Install mode must be skills or full.")
        invalid = sorted(set(agents) - set(PROVIDERS))
        if invalid:
            raise InstallError(f"Unknown providers: {', '.join(invalid)}")
        previous_state = self.state()
        if previous_state.get("install_mode") == "full" and mode == "skills":
            raise InstallError("A full installation cannot be downgraded with skills.sh; use `opencrow update` or rerun install.sh.")
        package_methods = merge_package_history(
            previous_state.get("package_methods", {}) if isinstance(previous_state.get("package_methods"), dict) else {},
            package_methods or {},
        )
        compatibility = self.provider_compatibility(agents, root=source.resolve())
        self._reject_incompatible(compatibility)
        stage = self._stage(source.resolve(), mode)
        try:
            self._validate_stage(stage, agents)
        except Exception:
            shutil.rmtree(stage, ignore_errors=True)
            raise
        self._commit_stage(stage)
        backups: list[dict[str, Any]] = []
        managed_paths = self._install_launchers(mode, toolboxes or [])
        self._remove_stale_launchers(previous_state.get("managed_paths", []), managed_paths)
        for provider in set(previous_state.get("selected_agents", [])) - set(agents):
            self._remove_integration_config(str(provider), backups)
        managed_paths.extend(self._install_skills(agents, backups))
        integration_paths, compatibility = self._install_integrations(agents, backups, compatibility)
        managed_paths.extend(integration_paths)
        managed_paths.extend(self._configure_shells(backups))
        self._verify_installed_integrations(agents)
        state = {
            "schema_version": 2,
            "version": VERSION,
            "install_mode": mode,
            "selected_agents": agents,
            "selected_toolboxes": toolboxes or [],
            "selected_tools": tools or [],
            "managed_paths": sorted(set(managed_paths)),
            "managed_hashes": tree_hashes(self.paths.current),
            "package_methods": package_methods,
            "provider_compatibility": compatibility,
            "config_backups": backups,
            "config_ownership": "OpenCROW owns only named MCP/hook entries and marked blocks.",
            "installed_at": utc_now(),
            "updated_at": utc_now(),
        }
        self._write_state(state, previous=previous_state or None)
        return state

    def install_bundle(
        self,
        *,
        bundle: Path,
        mode: str,
        agents: list[str],
        toolboxes: list[str] | None = None,
        tools: list[str] | None = None,
        package_methods: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        temporary = self._extract_verified_bundle(bundle)
        try:
            return self.install(
                source=self._find_bundle_root(temporary),
                mode=mode,
                agents=agents,
                toolboxes=toolboxes,
                tools=tools,
                package_methods=package_methods,
            )
        finally:
            shutil.rmtree(temporary, ignore_errors=True)

    def update(self, *, source: Path | None, bundle: Path | None, version: str | None) -> dict[str, Any]:
        current_state = self.state()
        if not current_state:
            raise InstallError("OpenCROW is not installed; run install.sh or skills.sh first.")
        temporary: Path | None = None
        try:
            if bundle:
                temporary = self._extract_verified_bundle(bundle)
                source = self._find_bundle_root(temporary)
            if source is None:
                source = self._download_release_source(version)
                temporary = source
            return self.install(
                source=source,
                mode=str(current_state.get("install_mode", "skills")),
                agents=list(current_state.get("selected_agents", [])),
                toolboxes=list(current_state.get("selected_toolboxes", [])),
                tools=list(current_state.get("selected_tools", [])),
                package_methods=dict(current_state.get("package_methods", {})),
            )
        finally:
            if temporary and temporary.exists():
                shutil.rmtree(temporary, ignore_errors=True)

    def _extract_verified_bundle(self, bundle: Path) -> Path:
        bundle = bundle.expanduser().resolve()
        if not bundle.is_file() or not zipfile.is_zipfile(bundle):
            raise InstallError(f"Local bundle is not a ZIP archive: {bundle}")
        target = Path(tempfile.mkdtemp(prefix="opencrow-bundle-"))
        with zipfile.ZipFile(bundle) as archive:
            for member in archive.infolist():
                relative = PurePosixPath(member.filename.replace("\\", "/"))
                if relative.is_absolute() or ".." in relative.parts or member.filename.startswith(("/", "\\")):
                    raise InstallError(f"Unsafe bundle member: {member.filename}")
                destination = (target / Path(*relative.parts)).resolve()
                destination.relative_to(target.resolve())
                if member.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output)
        manifest_candidates = list(target.rglob("release-manifest.json"))
        checksum_candidates = list(target.rglob("checksums.json"))
        if not manifest_candidates or not checksum_candidates:
            shutil.rmtree(target, ignore_errors=True)
            raise InstallError("Bundle lacks release-manifest.json or checksums.json.")
        checksum_root = checksum_candidates[0].parent
        expected = json.loads(checksum_candidates[0].read_text(encoding="utf-8"))
        if not isinstance(expected, dict):
            raise InstallError("Bundle checksums.json must be an object.")
        for relative, digest in expected.items():
            path = checksum_root / str(relative)
            if not path.is_file() or sha256_file(path) != digest:
                raise InstallError(f"Bundle checksum failed: {relative}")
        return target

    @staticmethod
    def _find_bundle_root(target: Path) -> Path:
        for marker in target.rglob("packages/lifecycle"):
            candidate = marker.parents[1]
            if (candidate / "installer/opencrow_manager.py").is_file():
                return candidate
        raise InstallError("Bundle does not contain an OpenCROW source tree.")

    def _download_release_source(self, version: str | None) -> Path:
        base = os.environ.get("OPENCROW_RELEASE_BASE_URL", "https://github.com/02loveslollipop/OpenCROW/releases/download")
        tag = version or "latest"
        if tag == "latest" and base.endswith("/download"):
            release_root = f"{base.removesuffix('/download').rstrip('/')}/latest/download"
        else:
            release_root = f"{base.rstrip('/')}/{tag}"
        url = f"{release_root}/opencrow-full.zip"
        checksums_url = f"{release_root}/release-checksums.txt"
        temporary = Path(tempfile.mkdtemp(prefix="opencrow-update-"))
        archive = temporary / "bundle.zip"
        checksum_path = temporary / "release-checksums.txt"
        try:
            with urllib.request.urlopen(url, timeout=30) as response, archive.open("wb") as output:
                shutil.copyfileobj(response, output)
            with urllib.request.urlopen(checksums_url, timeout=30) as response, checksum_path.open("wb") as output:
                shutil.copyfileobj(response, output)
            expected = None
            for line in checksum_path.read_text(encoding="utf-8").splitlines():
                fields = line.split()
                if len(fields) == 2 and fields[1].lstrip("*") == "opencrow-full.zip":
                    expected = fields[0]
                    break
            if expected is None or not re.fullmatch(r"[a-fA-F0-9]{64}", expected):
                raise InstallError("Release checksums do not contain opencrow-full.zip.")
            if sha256_file(archive) != expected.lower():
                raise InstallError("Downloaded opencrow-full.zip failed release checksum verification.")
            extracted = self._extract_verified_bundle(archive)
            shutil.rmtree(temporary, ignore_errors=True)
            return extracted
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    def rollback(self) -> dict[str, Any]:
        if not self.paths.previous.is_dir() or not self.paths.previous_manifest.is_file():
            raise InstallError("No prior successful managed snapshot is available.")
        temporary = self.paths.data / ".rollback-current"
        if temporary.exists():
            shutil.rmtree(temporary)
        os.replace(self.paths.current, temporary)
        try:
            os.replace(self.paths.previous, self.paths.current)
            os.replace(temporary, self.paths.previous)
        except Exception:
            if not self.paths.current.exists() and temporary.exists():
                os.replace(temporary, self.paths.current)
            raise
        current_state = self.state()
        previous_state = json.loads(self.paths.previous_manifest.read_text(encoding="utf-8"))
        backups: list[dict[str, Any]] = []
        launchers = self._install_launchers(
            str(previous_state.get("install_mode", "skills")),
            list(previous_state.get("selected_toolboxes", [])),
        )
        self._remove_stale_launchers(current_state.get("managed_paths", []), launchers)
        previous_agents = list(previous_state.get("selected_agents", []))
        for provider in set(current_state.get("selected_agents", [])) - set(previous_agents):
            self._remove_integration_config(str(provider), backups)
        self._install_skills(previous_agents, backups)
        self._install_integrations(previous_agents, backups)
        self._configure_shells(backups)
        self._write_state(previous_state, previous=current_state)
        return previous_state

    def integration_status(self) -> list[dict[str, Any]]:
        state = self.state()
        selected = set(state.get("selected_agents", []))
        root = self.paths.current if self.paths.current.is_dir() else source_root()
        compatibility = self.provider_compatibility(PROVIDERS, root=root)
        result: list[dict[str, Any]] = []
        for provider in PROVIDERS:
            provider_compatibility = compatibility[provider]
            version = provider_compatibility["version"]
            skill_dir = self.paths.home / SKILLS_DIRS[provider]
            lifecycle_skills = list(skill_dir.glob("*/SKILL.md")) if skill_dir.exists() else []
            result.append(
                {
                    "provider": provider,
                    "selected": provider in selected,
                    "available": version is not None,
                    "version": version,
                    "minimum_version": provider_compatibility["minimum_version"],
                    "compatibility": provider_compatibility["compatibility"],
                    "warning": provider_compatibility["warning"],
                    "skill_count": len(lifecycle_skills),
                    "healthy": provider not in selected or (
                        version is not None
                        and provider_compatibility["compatibility"] != "incompatible"
                        and bool(lifecycle_skills)
                    ),
                }
            )
        return result

    def repair(self) -> dict[str, Any]:
        state = self.state()
        if not state:
            raise InstallError("OpenCROW is not installed.")
        backups: list[dict[str, Any]] = []
        agents = list(state.get("selected_agents", []))
        compatibility = self.provider_compatibility(agents)
        self._reject_incompatible(compatibility)
        managed = self._install_launchers(
            str(state.get("install_mode", "skills")),
            list(state.get("selected_toolboxes", [])),
        )
        self._remove_stale_launchers(state.get("managed_paths", []), managed)
        managed.extend(self._install_skills(agents, backups))
        integration, compatibility = self._install_integrations(agents, backups, compatibility)
        state["managed_paths"] = sorted(set(state.get("managed_paths", [])) | set(managed) | set(integration))
        state["provider_compatibility"] = compatibility
        state["config_backups"] = list(state.get("config_backups", [])) + backups
        state["updated_at"] = utc_now()
        self._write_state(state)
        return state

    def doctor(self) -> dict[str, Any]:
        state = self.state()
        issues: list[str] = []
        warnings: list[str] = []
        if not state:
            issues.append("OpenCROW desired-state manifest is missing.")
        if state and not self.paths.current.is_dir():
            issues.append("Managed current snapshot is missing.")
        expected = state.get("managed_hashes", {}) if state else {}
        actual = tree_hashes(self.paths.current)
        for relative, digest in expected.items():
            if actual.get(relative) != digest:
                issues.append(f"Managed asset changed or is missing: {relative}")
        integrations = self.integration_status()
        for item in integrations:
            if item["selected"] and not item["healthy"]:
                if item["compatibility"] == "incompatible":
                    issues.append(str(item["warning"]))
                else:
                    issues.append(f"Integration is unhealthy: {item['provider']}")
            if item["selected"] and item["compatibility"] == "unknown" and item["warning"]:
                warnings.append(str(item["warning"]))
        python_candidates = [
            os.environ.get("OPENCROW_PYTHON"),
            str(self.paths.data / "envs/ctf/bin/python"),
            os.environ.get("OPENCROW_HELPER_PYTHON"),
            str(self.paths.data / "helper/bin/python"),
            str(self.paths.data / "helper/bin/python3"),
            shutil.which("python3"),
            shutil.which("python"),
        ]
        python = next(
            (
                candidate
                for candidate in python_candidates
                if candidate and Path(candidate).is_file()
            ),
            None,
        )
        if not python:
            issues.append("No lifecycle Python interpreter is available.")
        return {
            "ok": not issues,
            "version": state.get("version") if state else None,
            "mode": state.get("install_mode") if state else None,
            "platform": {"system": platform.system(), "machine": platform.machine()},
            "python": python,
            "integrations": integrations,
            "issues": issues,
            "warnings": warnings,
        }

    def _remove_integration_config(self, provider: str, backups: list[dict[str, Any]] | None = None) -> None:
        backups = backups if backups is not None else []
        if provider == "codex":
            config = self.paths.home / ".codex/config.toml"
            if config.exists():
                self._backup(config, backups)
                text = re.sub(
                    re.escape(MANAGED_TOML_START) + r".*?" + re.escape(MANAGED_TOML_END),
                    "",
                    config.read_text(encoding="utf-8"),
                    flags=re.DOTALL,
                ).strip()
                atomic_text(config, text + ("\n" if text else ""))
            hooks = self.paths.home / ".codex/hooks.json"
            if hooks.exists():
                self._backup(hooks, backups)
                value = json.loads(hooks.read_text(encoding="utf-8"))
                atomic_text(hooks, json.dumps(remove_opencrow_hooks(value), indent=2, sort_keys=True) + "\n")
            return
        if provider in JSON_CONFIGS:
            relative, _ = JSON_CONFIGS[provider]
            config = self.paths.home / relative
            if config.exists():
                self._backup(config, backups)
                value = json.loads(config.read_text(encoding="utf-8"))
                cleaned = remove_opencrow_hooks(value)
                for parent_key in ("mcp", "mcpServers"):
                    parent = cleaned.get(parent_key)
                    if isinstance(parent, dict):
                        parent.pop("opencrow-lifecycle", None)
                        servers = parent.get("servers")
                        if isinstance(servers, dict):
                            servers.pop("opencrow-lifecycle", None)
                atomic_text(config, json.dumps(cleaned, indent=2, sort_keys=True) + "\n")
        if provider == "opencode":
            plugin = self.paths.home / ".config/opencode/plugins/opencrow-lifecycle.js"
            if plugin.exists():
                plugin.unlink()
        if provider == "antigravity":
            mcp = self.paths.home / ".gemini/antigravity-cli/mcp_config.json"
            if mcp.exists():
                self._backup(mcp, backups)
                value = json.loads(mcp.read_text(encoding="utf-8"))
                if isinstance(value.get("mcpServers"), dict):
                    value["mcpServers"].pop("opencrow-lifecycle", None)
                atomic_text(mcp, json.dumps(value, indent=2, sort_keys=True) + "\n")

    def _remove_stale_launchers(self, old_managed: Iterable[str], desired: Iterable[str]) -> None:
        desired_paths = {Path(value) for value in desired}
        for value in old_managed:
            path = Path(value)
            if path.parent != self.paths.bin or path in desired_paths:
                continue
            if path.is_file() and self._is_managed_launcher(path):
                path.unlink()

    def _remove_shell_config(self) -> None:
        start = "# >>> OpenCROW PATH >>>"
        end = "# <<< OpenCROW PATH <<<"
        for relative in (".bashrc", ".zshrc"):
            destination = self.paths.home / relative
            if not destination.exists():
                continue
            text = re.sub(
                re.escape(start) + r".*?" + re.escape(end),
                "",
                destination.read_text(encoding="utf-8"),
                flags=re.DOTALL,
            ).strip()
            atomic_text(destination, text + ("\n" if text else ""))
        fish = self.paths.home / ".config/fish/conf.d/opencrow.fish"
        if fish.exists():
            lines = [line for line in fish.read_text(encoding="utf-8").splitlines() if str(self.paths.bin) not in line]
            if lines:
                atomic_text(fish, "\n".join(lines) + "\n")
            else:
                fish.unlink()

    def _purge_system_packages(self, state: dict[str, Any]) -> tuple[list[str], list[str]]:
        package_state = state.get("package_methods", {}).get("os_packages", {})
        packages = [str(value) for value in package_state.get("installed_by_opencrow", []) if str(value)]
        if not packages:
            return [], []
        manager = str(package_state.get("method", ""))
        commands = {
            "apt": ["apt-get", "remove", "-y", *packages],
            "dnf": ["dnf", "remove", "-y", *packages],
            "yum": ["yum", "remove", "-y", *packages],
            "pacman": ["pacman", "-R", "--noconfirm", *packages],
        }
        command = commands.get(manager)
        if command is None:
            return [], [f"Unsupported recorded package purge method `{manager}` for: {', '.join(packages)}"]
        if os.geteuid() != 0:
            sudo_available = bool(shutil.which("sudo")) and subprocess.run(
                ["sudo", "-n", "true"], capture_output=True, check=False
            ).returncode == 0
            if sudo_available:
                command = ["sudo", "-n", *command]
            else:
                return [], ["System purge needs passwordless sudo or an elevated invocation: " + shlex_join(command)]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode:
            return [], [f"System package purge failed ({shlex_join(command)}): {(result.stderr or result.stdout).strip()}"]
        return packages, []

    def _purge_agent_clis(self, state: dict[str, Any]) -> tuple[list[str], list[str]]:
        cli_state = state.get("package_methods", {}).get("agent_clis", {})
        providers = [str(value) for value in cli_state.get("installed", []) if str(value)]
        removed: list[str] = []
        unresolved: list[str] = []
        commands = {
            "codex": ["npm", "uninstall", "--global", "--prefix", str(self.paths.home / ".local"), "@openai/codex"],
            "opencode": ["opencode", "uninstall", "--force", "--keep-config", "--keep-data"],
        }
        for provider in providers:
            command = commands.get(provider)
            if command is None and provider in {"claude", "antigravity"}:
                receipts = cli_state.get("receipts", {}) if isinstance(cli_state.get("receipts"), dict) else {}
                receipt = receipts.get(provider, {}) if isinstance(receipts.get(provider), dict) else {}
                owned = receipt.get("owned_paths", []) if isinstance(receipt.get("owned_paths"), list) else []
                if not owned:
                    unresolved.append(f"{provider}: no OpenCROW ownership receipt is available; user data was preserved")
                    continue
                failures: list[str] = []
                deleted = 0
                for item in owned:
                    path_value = item.get("path") if isinstance(item, dict) else None
                    if not isinstance(path_value, str):
                        failures.append("receipt contains an invalid path")
                        continue
                    path = Path(path_value)
                    if path == self.paths.home or self.paths.home not in path.parents:
                        failures.append(f"unsafe receipt path was preserved: {path}")
                        continue
                    if provider == "claude" and path == self.paths.home / ".claude":
                        failures.append(f"configuration path was preserved: {path}")
                        continue
                    if path.is_dir() and not path.is_symlink():
                        shutil.rmtree(path)
                        deleted += 1
                    elif path.exists() or path.is_symlink():
                        path.unlink()
                        deleted += 1
                if failures:
                    unresolved.extend(f"{provider}: {failure}" for failure in failures)
                elif deleted:
                    removed.append(provider)
                else:
                    unresolved.append(f"{provider}: receipt-owned paths were already absent")
                continue
            if command is None:
                unresolved.append(f"{provider}: no safe uninstall strategy is recorded")
                continue
            if shutil.which(command[0]) is None:
                unresolved.append(f"{provider}: purge command is unavailable: {command[0]}")
                continue
            result = subprocess.run(command, capture_output=True, text=True, check=False)
            if result.returncode:
                unresolved.append(f"{provider}: vendor uninstall failed: {(result.stderr or result.stdout).strip()}")
            else:
                removed.append(provider)
        return removed, unresolved

    def uninstall(self, *, purge_env: bool, purge_system: bool, purge_agent_clis: bool) -> dict[str, Any]:
        state = self.state()
        purged_packages, system_unresolved = self._purge_system_packages(state) if purge_system else ([], [])
        purged_clis, cli_unresolved = self._purge_agent_clis(state) if purge_agent_clis else ([], [])
        agents = list(state.get("selected_agents", []))
        for provider in agents:
            self._remove_provider_skills(provider)
            self._remove_integration_config(provider)
        for value in state.get("managed_paths", []):
            path = Path(value)
            if path.parent == self.paths.bin and path.exists() and self._is_managed_launcher(path):
                path.unlink()
        self._remove_shell_config()
        removed = [str(self.paths.current), str(self.paths.previous), str(self.paths.manifest)]
        for path in (self.paths.current, self.paths.previous):
            if path.exists():
                shutil.rmtree(path)
        for path in (self.paths.manifest, self.paths.previous_manifest):
            if path.exists():
                path.unlink()
        update_cache = self.paths.state / "update-cache.json"
        if update_cache.exists():
            update_cache.unlink()
            removed.append(str(update_cache))
        retained: list[str] = [str(self.paths.backups)] if self.paths.backups.exists() else []
        if purge_env:
            for path in (self.paths.data / "helper", self.paths.data / "miniconda", self.paths.data / "envs"):
                if path.exists():
                    shutil.rmtree(path)
                    removed.append(str(path))
        if purge_system:
            removed.extend(f"system-package:{name}" for name in purged_packages)
            retained.extend(system_unresolved)
        if purge_agent_clis:
            removed.extend(f"agent-cli:{name}" for name in purged_clis)
            retained.extend(cli_unresolved)
        unresolved = [*system_unresolved, *cli_unresolved]
        return {"ok": not unresolved, "removed": removed, "retained": retained, "unresolved": unresolved}


def shlex_quote(value: str) -> str:
    import shlex

    return shlex.quote(value)


def shlex_join(values: Iterable[str]) -> str:
    import shlex

    return shlex.join(values)


def source_root() -> Path:
    override = os.environ.get("OPENCROW_SOURCE_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parents[1]


def parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = re.search(r"(?:^|v)(\d+)\.(\d+)\.(\d+)", value)
    return tuple(int(item) for item in match.groups()) if match else (0, 0, 0)


def refresh_update_cache(paths: Paths) -> int:
    url = os.environ.get("OPENCROW_STABLE_MANIFEST_URL", "https://opencrow.02labs.me/release-manifest.json")
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            value = json.load(response)
        if not isinstance(value, dict) or not isinstance(value.get("version"), str):
            return 1
        value["checked_at_epoch"] = int(time.time())
        atomic_text(paths.state / "update-cache.json", json.dumps(value, indent=2, sort_keys=True) + "\n")
        return 0
    except Exception:
        return 1


def maybe_show_update_notice(paths: Paths) -> None:
    cache = paths.state / "update-cache.json"
    value: dict[str, Any] = {}
    try:
        loaded = json.loads(cache.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            value = loaded
    except (OSError, json.JSONDecodeError):
        pass
    available = str(value.get("version", ""))
    if _version_tuple(available) > _version_tuple(VERSION):
        print(f"OpenCROW {available} is available; run `opencrow update` to apply it.", file=sys.stderr)
    if int(time.time()) - int(value.get("checked_at_epoch", 0)) < 24 * 60 * 60:
        return
    try:
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "internal-update-check"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="opencrow", description="Manage an OpenCROW v2 installation.")
    parser.add_argument("--version", action="version", version=f"OpenCROW {VERSION}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    install = subparsers.add_parser("internal-install", help=argparse.SUPPRESS)
    source_group = install.add_mutually_exclusive_group()
    source_group.add_argument("--source", type=Path)
    source_group.add_argument("--bundle", type=Path)
    install.add_argument("--mode", choices=["skills", "full"], required=True)
    install.add_argument("--agents", default="")
    install.add_argument("--toolboxes", default="")
    install.add_argument("--tools", default="")
    install.add_argument("--package-methods-json", default="{}")

    update = subparsers.add_parser("update", help="Stage, verify, and explicitly apply an update.")
    update.add_argument("--version", dest="release_version")
    update.add_argument("--bundle", type=Path)
    update.add_argument("--source", type=Path, help=argparse.SUPPRESS)
    subparsers.add_parser("rollback", help="Restore the prior successful managed snapshot.")
    subparsers.add_parser("doctor", help="Verify managed assets and provider integrations.")
    integrations = subparsers.add_parser("integrations", help="List or repair integrations.")
    integration_sub = integrations.add_subparsers(dest="integration_command", required=True)
    integration_sub.add_parser("list")
    integration_sub.add_parser("repair")
    uninstall = subparsers.add_parser("uninstall", help="Remove OpenCROW-managed files and config entries.")
    uninstall.add_argument("--purge-env", action="store_true")
    uninstall.add_argument("--purge-system", action="store_true")
    uninstall.add_argument("--purge-agent-clis", action="store_true")
    subparsers.add_parser("internal-update-check", help=argparse.SUPPRESS)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    engine = StateEngine()
    try:
        if args.command == "internal-update-check":
            return refresh_update_cache(engine.paths)
        if args.command not in {"internal-install", "uninstall"}:
            maybe_show_update_notice(engine.paths)
        if args.command == "internal-install":
            arguments = {
                "mode": args.mode,
                "agents": parse_csv(args.agents),
                "toolboxes": parse_csv(args.toolboxes),
                "tools": parse_csv(args.tools),
                "package_methods": json.loads(args.package_methods_json),
            }
            if args.bundle:
                result = engine.install_bundle(bundle=args.bundle, **arguments)
            else:
                result = engine.install(source=args.source or source_root(), **arguments)
        elif args.command == "update":
            result = engine.update(source=args.source, bundle=args.bundle, version=args.release_version)
        elif args.command == "rollback":
            result = engine.rollback()
        elif args.command == "doctor":
            result = engine.doctor()
        elif args.command == "integrations" and args.integration_command == "list":
            result = {"integrations": engine.integration_status()}
        elif args.command == "integrations" and args.integration_command == "repair":
            result = engine.repair()
        elif args.command == "uninstall":
            result = engine.uninstall(
                purge_env=args.purge_env,
                purge_system=args.purge_system,
                purge_agent_clis=args.purge_agent_clis,
            )
        else:
            raise InstallError("Unsupported command")
        print_json(result)
        return 0 if result.get("ok", True) else 1
    except (InstallError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"opencrow: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
