"""Unit tests for install_cli.py helper structures."""

from __future__ import annotations

from pathlib import Path
import pytest

from install_cli import InstallerContext, ROOT_DIR


def test_installer_context(tmp_path):
    ctx = InstallerContext(
        root_dir=ROOT_DIR,
        env_name="ctf",
        dry_run=True,
        target_user="testuser",
        target_home=tmp_path,
        conda_bin=tmp_path / "bin/conda",
    )
    assert ctx.env_name == "ctf"
    assert ctx.dry_run is True
    assert ctx.target_home == tmp_path
    env = ctx.target_env()
    assert env["HOME"] == str(tmp_path)
    assert env["OPENCROW_HOME"] == str(tmp_path)
    assert str(tmp_path / ".local/bin") in ctx.target_path
