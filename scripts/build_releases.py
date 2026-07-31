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

    pages_dir = ROOT_DIR / "dist-pages"
    if pages_dir.exists():
        shutil.rmtree(pages_dir)
    (pages_dir / "releases").mkdir(parents=True, exist_ok=True)
    (pages_dir / "release").mkdir(parents=True, exist_ok=True)

    opencrow_sh_source = ROOT_DIR / "scripts" / "opencrow.sh"
    shutil.copy2(opencrow_sh_source, pages_dir / "releases" / "cli.sh")
    shutil.copy2(opencrow_sh_source, pages_dir / "releases" / "opencrow-cli.sh")
    shutil.copy2(opencrow_sh_source, pages_dir / "release" / "opencrow-cli.sh")
    shutil.copy2(opencrow_sh_source, pages_dir / "opencrow-cli.sh")
    shutil.copy2(opencrow_sh_source, pages_dir / "opencrow.sh")
    shutil.copy2(opencrow_sh_source, pages_dir / "cli.sh")

    # Cloudflare Pages _redirects file for root URL redirect
    redirects_content = "/ https://github.com/02loveslollipop/OpenCROW 302\n"
    (pages_dir / "_redirects").write_text(redirects_content, encoding="utf-8")

    # Fallback index.html with meta refresh redirect to GitHub repository
    index_html_content = """<!DOCTYPE html>
<html>
<head>
  <meta http-equiv="refresh" content="0; url=https://github.com/02loveslollipop/OpenCROW">
  <link rel="canonical" href="https://github.com/02loveslollipop/OpenCROW">
  <title>Redirecting to OpenCROW GitHub Repository...</title>
</head>
<body>
  <p>Redirecting to <a href="https://github.com/02loveslollipop/OpenCROW">OpenCROW GitHub Repository</a>...</p>
</body>
</html>
"""
    (pages_dir / "index.html").write_text(index_html_content, encoding="utf-8")

    print(f"[+] Prepared Cloudflare Pages assets & root redirect in {pages_dir}")

    print("==> Release build completed successfully.")


if __name__ == "__main__":
    main()
