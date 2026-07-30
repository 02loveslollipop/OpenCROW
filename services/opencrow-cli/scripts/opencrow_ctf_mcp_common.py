#!/usr/bin/env python3
"""Shared helpers for OpenCROW MCP servers that rely on the ctf conda environment."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from opencrow_mcp_core import merge_env, normalize_path, run_command


JSON = dict[str, Any]


def conda_run(
    args: list[str],
    *,
    env_name: str = "ctf",
    cwd: str | Path | None = None,
    timeout_sec: int = 120,
    extra_env: dict[str, str] | None = None,
) -> JSON:
    return run_command(
        ["conda", "run", "-n", env_name, *args],
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
