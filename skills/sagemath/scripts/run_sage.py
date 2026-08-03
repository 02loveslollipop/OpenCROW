#!/usr/bin/env python3
"""Run SageMath code or a .sage file with the best detected Sage runtime."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))
from python_runtime import sage_command  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Execute SageMath code using an override, the sage environment, or PATH."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--code", help="Inline SageMath code to execute.")
    source.add_argument("--file", type=Path, help="Path to a .sage file to execute.")
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Timeout in seconds for the SageMath process. Default: 120.",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep the generated temporary .sage file when using --code.",
    )
    parser.add_argument(
        "--keep-generated",
        action="store_true",
        help="Keep Sage-generated .sage.py sidecar files.",
    )
    return parser


def run_sage_file(path: Path, timeout: int, keep_generated: bool) -> int:
    sidecar = Path(f"{path}.py")
    sidecar_existed = sidecar.exists()
    try:
        cmd = [*sage_command(), str(path)]
        completed = subprocess.run(cmd, check=False, timeout=timeout)
    except (FileNotFoundError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 127
    except subprocess.TimeoutExpired:
        print(f"SageMath execution timed out after {timeout} seconds.", file=sys.stderr)
        return 124
    finally:
        if not keep_generated and not sidecar_existed and sidecar.exists():
            sidecar.unlink()
    return completed.returncode


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.file is not None:
        file_path = args.file.expanduser().resolve()
        if not file_path.exists():
            print(f"Input file does not exist: {file_path}", file=sys.stderr)
            return 2
        if file_path.suffix != ".sage":
            print(f"Expected a .sage file, got: {file_path.name}", file=sys.stderr)
            return 2
        return run_sage_file(file_path, args.timeout, args.keep_generated)

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sage", prefix="opencrow-sagemath-", delete=False
        ) as handle:
            handle.write(args.code)
            temp_path = Path(handle.name)
        return run_sage_file(temp_path, args.timeout, args.keep_generated)
    finally:
        if temp_path is not None and temp_path.exists() and not args.keep_temp:
            temp_path.unlink()


if __name__ == "__main__":
    sys.exit(main())
