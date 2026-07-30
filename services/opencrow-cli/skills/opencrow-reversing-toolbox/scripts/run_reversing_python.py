#!/usr/bin/env python3
"""Run Python code or a Python file inside a conda environment for reversing work."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Execute Python code or a Python file via 'conda run -n ENV python'."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--code", help="Inline Python code to execute.")
    source.add_argument("--file", type=Path, help="Path to a Python file to execute.")
    parser.add_argument(
        "--env",
        default="ctf",
        help="Conda environment to use. Default: ctf.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Timeout in seconds for the Python process. Default: 120.",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep the generated temporary .py file when using --code.",
    )
    return parser


def run_python_file(path: Path, env_name: str, timeout: int) -> int:
    cmd = ["conda", "run", "-n", env_name, "python", str(path)]
    try:
        completed = subprocess.run(cmd, check=False, timeout=timeout)
    except FileNotFoundError:
        print("conda was not found in PATH.", file=sys.stderr)
        return 127
    except subprocess.TimeoutExpired:
        print(f"Python execution timed out after {timeout} seconds.", file=sys.stderr)
        return 124
    return completed.returncode


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.file is not None:
        file_path = args.file.expanduser().resolve()
        if not file_path.exists():
            print(f"Input file does not exist: {file_path}", file=sys.stderr)
            return 2
        if file_path.suffix != ".py":
            print(f"Expected a .py file, got: {file_path.name}", file=sys.stderr)
            return 2
        return run_python_file(file_path, args.env, args.timeout)

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", prefix="codex-opencrow-reversing-", delete=False
        ) as handle:
            handle.write(args.code)
            temp_path = Path(handle.name)
        return run_python_file(temp_path, args.env, args.timeout)
    finally:
        if temp_path is not None and temp_path.exists() and not args.keep_temp:
            temp_path.unlink()


if __name__ == "__main__":
    sys.exit(main())
