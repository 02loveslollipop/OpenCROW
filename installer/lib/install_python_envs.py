#!/usr/bin/env python3
"""Provision full-install Python environments under OpenCROW-owned paths."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def run(command: list[str]) -> tuple[bool, str]:
    process = subprocess.run(command, text=True, capture_output=True, check=False)
    if process.stdout:
        print(process.stdout, file=sys.stderr, end="")
    if process.stderr:
        print(process.stderr, file=sys.stderr, end="")
    detail = (process.stderr or process.stdout).strip().splitlines()
    return process.returncode == 0, detail[-1] if detail else f"exit {process.returncode}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--conda")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--toolboxes", default="")
    args = parser.parse_args()

    conda = str(Path(args.conda).resolve()) if args.conda else None
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    selected = [value for value in args.toolboxes.split(",") if value]
    env_root = args.data_root / "envs"
    env_root.mkdir(parents=True, exist_ok=True)
    method = "managed-conda-prefix" if conda else "managed-venv"
    result: dict[str, object] = {"method": method, "installed": [], "unresolved": []}

    toolbox_packages = manifest["ctf"]["toolboxes"]
    pip_packages = list(
        dict.fromkeys(
            [*manifest["ctf"].get("runtime_packages", [])]
            + [
                package
                for toolbox in selected
                for package in toolbox_packages.get(toolbox, [])
            ]
        )
    )
    prefix = env_root / "ctf"
    python = prefix / "bin" / "python"
    if not python.is_file():
        if conda:
            ok, detail = run(
                [conda, "create", "--yes", "--prefix", str(prefix), f"python={manifest['ctf']['python']}", "pip"]
            )
        else:
            ok, detail = run([sys.executable, "-m", "venv", str(prefix)])
        if not ok:
            result["unresolved"].append(f"ctf environment: {detail}")  # type: ignore[union-attr]
    if python.is_file():
        result["installed"].append("ctf")  # type: ignore[union-attr]
        for package in pip_packages:
            ok, detail = run([str(python), "-m", "pip", "install", "--disable-pip-version-check", package])
            if not ok:
                result["unresolved"].append(f"ctf package {package}: {detail}")  # type: ignore[union-attr]

    sage = manifest["sage"]
    if sage["toolbox"] in selected:
        prefix = env_root / "sage"
        executable = prefix / "bin" / "sage"
        if not conda:
            result["unresolved"].append("sage environment: Conda is required for the managed SageMath package")  # type: ignore[union-attr]
        elif not executable.is_file():
            command = [conda, "create", "--yes", "--prefix", str(prefix)]
            for channel in sage["channels"]:
                command.extend(["--channel", channel])
            command.extend(sage["packages"])
            ok, detail = run(command)
            if not ok:
                result["unresolved"].append(f"sage environment: {detail}")  # type: ignore[union-attr]
        if executable.is_file():
            result["installed"].append("sage")  # type: ignore[union-attr]

    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
