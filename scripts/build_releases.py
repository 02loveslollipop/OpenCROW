#!/usr/bin/env python3
"""Build script for OpenCROW GitHub Release ZIP packages."""

from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DIST_DIR = ROOT_DIR / "dist"
CLI_DIR = ROOT_DIR / "services" / "opencrow-cli"
CONSTELLATION_DIR = ROOT_DIR / "services" / "constellation"


def zip_directory(source_dir: Path, zip_path: Path, extra_sources: list[tuple[Path, str]] | None = None) -> None:
    print(f"[*] Packaging {source_dir.name} into {zip_path}...")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in source_dir.rglob("*"):
            if "__pycache__" in file_path.parts or file_path.suffix == ".pyc":
                continue
            arcname = file_path.relative_to(source_dir)
            zf.write(file_path, arcname)

        for src_path, target_arcname in extra_sources or []:
            if src_path.is_dir():
                for file_path in src_path.rglob("*"):
                    if "__pycache__" in file_path.parts or file_path.suffix == ".pyc":
                        continue
                    rel = file_path.relative_to(src_path)
                    zf.write(file_path, Path(target_arcname) / rel)
            elif src_path.is_file():
                zf.write(src_path, target_arcname)

    print(f"[+] Successfully created {zip_path} ({zip_path.stat().st_size} bytes)")


def main() -> None:
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    if not CLI_DIR.exists():
        print(f"Error: {CLI_DIR} does not exist", file=sys.stderr)
        sys.exit(1)
    if not CONSTELLATION_DIR.exists():
        print(f"Error: {CONSTELLATION_DIR} does not exist", file=sys.stderr)
        sys.exit(1)

    extra_cli_files = [
        (CONSTELLATION_DIR / "constellation", "constellation"),
        (CONSTELLATION_DIR / "requirements.txt", "requirements-constellation.txt"),
    ]

    zip_directory(CLI_DIR, DIST_DIR / "opencrow-cli.zip", extra_sources=extra_cli_files)
    zip_directory(CONSTELLATION_DIR, DIST_DIR / "opencrow-constellation.zip")

    worker_script_target = ROOT_DIR / "services" / "installer-worker" / "src" / "opencrow-cli.sh"
    worker_script_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT_DIR / "scripts" / "opencrow.sh", worker_script_target)
    print(f"[+] Synced opencrow.sh to {worker_script_target}")

    print("==> Release build completed successfully.")


if __name__ == "__main__":
    main()
