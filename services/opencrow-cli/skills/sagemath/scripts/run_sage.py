#!/usr/bin/env python3
"""Run SageMath code or a .sage file inside the conda environment named 'sage'."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Execute SageMath code or a .sage file via 'conda run -n sage sage'."
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
    cmd = ["conda", "run", "-n", "sage", "sage", str(path)]
    sidecar = Path(f"{path}.py")
    sidecar_existed = sidecar.exists()
    try:
        completed = subprocess.run(cmd, check=False, timeout=timeout)
    except FileNotFoundError:
        print("conda was not found in PATH.", file=sys.stderr)
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
            mode="w", suffix=".sage", prefix="codex-sagemath-", delete=False
        ) as handle:
            handle.write(args.code)
            temp_path = Path(handle.name)
        return run_sage_file(temp_path, args.timeout, args.keep_generated)
    finally:
        if temp_path is not None and temp_path.exists() and not args.keep_temp:
            temp_path.unlink()


if __name__ == "__main__":
    sys.exit(main())
