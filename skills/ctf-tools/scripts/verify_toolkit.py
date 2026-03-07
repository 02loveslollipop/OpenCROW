#!/usr/bin/env python3
"""Verify Python modules and system tools for the ctf CTF toolkit."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


PYTHON_MODULES = [
    "z3",
    "pwn",
    "angr",
    "claripy",
    "capstone",
    "unicorn",
    "keystone",
    "ropper",
    "r2pipe",
    "lief",
    "scapy",
    "fpylll",
]

SYSTEM_TOOLS = [
    "gdb",
    "pwndbg",
    "gdbserver",
    "ghidra-headless",
    "pwninit",
    "seccomp-tools",
    "checksec",
    "patchelf",
    "qemu-aarch64",
    "qemu-aarch64-static",
    "qemu-arm",
    "qemu-x86_64",
    "r2",
    "objdump",
    "strace",
    "ltrace",
    "binwalk",
    "gcc",
    "nasm",
]


def check_python_modules() -> dict[str, bool]:
    code = (
        "import importlib.util as u, json\n"
        f"mods = {PYTHON_MODULES!r}\n"
        "print(json.dumps({m: bool(u.find_spec(m)) for m in mods}))\n"
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as handle:
        handle.write(code)
        temp_path = Path(handle.name)
    try:
        result = subprocess.run(
            ["conda", "run", "-n", "ctf", "python", str(temp_path)],
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        temp_path.unlink(missing_ok=True)
    return json.loads(result.stdout.strip())


def check_system_tools() -> dict[str, bool]:
    return {tool: shutil.which(tool) is not None for tool in SYSTEM_TOOLS}


def main() -> int:
    try:
        payload = {
            "python_modules": check_python_modules(),
            "system_tools": check_system_tools(),
        }
    except subprocess.CalledProcessError as exc:
        print(exc.stderr or str(exc), file=sys.stderr)
        return exc.returncode or 1

    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
