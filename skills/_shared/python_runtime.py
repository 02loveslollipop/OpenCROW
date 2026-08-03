"""Resolve a portable Python command for OpenCROW skills."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


def _conda_env_exists(name: str) -> bool:
    conda = shutil.which("conda")
    if not conda:
        return False
    try:
        result = subprocess.run(
            [conda, "env", "list", "--json"],
            capture_output=True,
            check=False,
            text=True,
            timeout=10,
        )
        payload = json.loads(result.stdout) if result.returncode == 0 else {}
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return False
    return any(Path(value).name == name for value in payload.get("envs", []))


def _managed_env(name: str) -> Path:
    data_home = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    return data_home / "opencrow" / "envs" / name


def python_command(preferred_env: str = "ctf") -> list[str]:
    """Return override, preferred Conda env, helper Python, then system Python."""

    override = os.environ.get("OPENCROW_PYTHON", "").strip()
    if override:
        command = shlex.split(override)
        if command and (Path(command[0]).is_file() or shutil.which(command[0])):
            return command
        raise RuntimeError(f"OPENCROW_PYTHON is not executable: {override}")
    managed_python = _managed_env(preferred_env) / "bin" / "python"
    if managed_python.is_file() and os.access(managed_python, os.X_OK):
        return [str(managed_python)]
    if _conda_env_exists(preferred_env):
        return [str(shutil.which("conda")), "run", "-n", preferred_env, "python"]
    helper_override = os.environ.get("OPENCROW_HELPER_PYTHON", "").strip()
    data_home = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    helper = Path(helper_override) if helper_override else data_home / "opencrow" / "helper" / "bin" / "python"
    if helper.is_file() and os.access(helper, os.X_OK):
        return [str(helper)]
    if sys.executable and Path(sys.executable).is_file():
        return [sys.executable]
    for name in ("python3", "python"):
        value = shutil.which(name)
        if value:
            return [value]
    raise RuntimeError("No usable Python found (override, ctf Conda env, OpenCROW helper, or system Python).")


def sage_command() -> list[str]:
    override = os.environ.get("OPENCROW_SAGE", "").strip()
    if override:
        command = shlex.split(override)
        if command and (Path(command[0]).is_file() or shutil.which(command[0])):
            return command
        raise RuntimeError(f"OPENCROW_SAGE is not executable: {override}")
    managed_sage = _managed_env("sage") / "bin" / "sage"
    if managed_sage.is_file() and os.access(managed_sage, os.X_OK):
        return [str(managed_sage)]
    if _conda_env_exists("sage"):
        return [str(shutil.which("conda")), "run", "-n", "sage", "sage"]
    sage = shutil.which("sage")
    if sage:
        return [sage]
    raise RuntimeError("SageMath is unavailable (OPENCROW_SAGE, sage Conda env, and PATH were checked).")
