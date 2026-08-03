#!/usr/bin/env python3
"""Shared helpers for OpenCROW MCP servers that rely on the ctf conda environment."""

from __future__ import annotations

import os
import shlex
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from opencrow_mcp_core import merge_env, normalize_path, run_command


JSON = dict[str, Any]


def _managed_env(env_name: str) -> Path:
    data_home = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    return data_home / "opencrow" / "envs" / env_name


def _conda_command() -> str | None:
    value = shutil.which("conda")
    if value:
        return value
    managed = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "opencrow" / "miniconda" / "bin" / "conda"
    return str(managed) if managed.is_file() else None


def python_command(env_name: str = "ctf") -> list[str]:
    override = os.environ.get("OPENCROW_PYTHON", "").strip()
    if override:
        command = shlex.split(override)
        if command and (Path(command[0]).is_file() or shutil.which(command[0])):
            return command
    managed_python = _managed_env(env_name) / "bin" / "python"
    if managed_python.is_file() and os.access(managed_python, os.X_OK):
        return [str(managed_python)]
    conda = _conda_command()
    if conda:
        probe = run_command([conda, "run", "-n", env_name, "python", "-c", "pass"], timeout_sec=15)
        if probe["ok"]:
            return [conda, "run", "-n", env_name, "python"]
    helper_override = os.environ.get("OPENCROW_HELPER_PYTHON", "").strip()
    data_home = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    helper = Path(helper_override) if helper_override else data_home / "opencrow" / "helper" / "bin" / "python"
    if helper.is_file() and os.access(helper, os.X_OK):
        return [str(helper)]
    return [sys.executable]


def conda_run(
    args: list[str],
    *,
    env_name: str = "ctf",
    cwd: str | Path | None = None,
    timeout_sec: int = 120,
    extra_env: dict[str, str] | None = None,
) -> JSON:
    if args and args[0] == "python":
        command = [*python_command(env_name), *args[1:]]
    elif (_managed_env(env_name) / "bin" / args[0]).is_file():
        command = [str(_managed_env(env_name) / "bin" / args[0]), *args[1:]]
    elif (conda := _conda_command()):
        command = [conda, "run", "-n", env_name, *args]
    else:
        command = args
    return run_command(
        command,
        cwd=cwd,
        timeout_sec=timeout_sec,
        env=merge_env(extra_env),
    )


def conda_command_exists(env_name: str, command_name: str) -> bool:
    result = conda_run(
        [
            "python",
            "-c",
            (
                "import shutil, sys\n"
                f"raise SystemExit(0 if shutil.which({command_name!r}) else 1)\n"
            ),
        ],
        env_name=env_name,
        timeout_sec=30,
    )
    return result["exit_code"] == 0


def run_conda_python(
    *,
    env_name: str = "ctf",
    code: str | None = None,
    path: str | Path | None = None,
    cwd: str | Path | None = None,
    timeout_sec: int = 120,
    prefix: str = "opencrow-ctf-",
) -> JSON:
    if (code is None) == (path is None):
        raise ValueError("Exactly one of `code` or `path` must be provided.")

    if path is not None:
        return conda_run(
            ["python", normalize_path(path) or str(path)],
            env_name=env_name,
            cwd=cwd,
            timeout_sec=timeout_sec,
        )

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            prefix=prefix,
            delete=False,
        ) as handle:
            handle.write(code or "")
            temp_path = Path(handle.name)
        return conda_run(
            ["python", str(temp_path)],
            env_name=env_name,
            cwd=cwd,
            timeout_sec=timeout_sec,
        )
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
