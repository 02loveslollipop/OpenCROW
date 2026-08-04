#!/usr/bin/env python3
"""Build the complete OpenCROW v2 release transaction payload."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from generate_wiki import build as build_wiki


ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
PAGES = ROOT / "dist-pages"
SKIP_PARTS = {".git", ".pytest_cache", "__pycache__", ".wrangler"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def git_value(*args: str, fallback: str) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip() or fallback
    except (OSError, subprocess.SubprocessError):
        return fallback


def ignored(path: Path) -> bool:
    return bool(SKIP_PARTS.intersection(path.parts)) or path.suffix == ".pyc"


def copy_entry(source: Path, destination: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, destination, ignore=lambda _root, names: [name for name in names if name in SKIP_PARTS or name.endswith(".pyc")])
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def bundle_manifest(stage: Path, *, version: str, mode: str, tag: str, sha: str) -> None:
    manifest = {
        "schema_version": 2,
        "version": version,
        "release_tag": tag,
        "source_commit": sha,
        "install_mode": mode,
        "built_at": utc_now(),
    }
    (stage / "release-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    checksums = {
        path.relative_to(stage).as_posix(): sha256(path)
        for path in sorted(stage.rglob("*"))
        if path.is_file() and path.name != "checksums.json" and not ignored(path)
    }
    (stage / "checksums.json").write_text(json.dumps(checksums, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def zip_tree(source: Path, destination: Path) -> None:
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(source.rglob("*")):
            if ignored(path) or not path.is_file():
                continue
            info = zipfile.ZipInfo(path.relative_to(source).as_posix())
            info.date_time = (2020, 1, 1, 0, 0, 0)
            info.external_attr = (path.stat().st_mode & 0xFFFF) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())


def stage_bundle(entries: Iterable[str], destination: Path, *, version: str, mode: str, tag: str, sha: str) -> None:
    with tempfile.TemporaryDirectory(prefix=f"opencrow-{mode}-") as temporary:
        stage = Path(temporary)
        for relative in entries:
            source = ROOT / relative
            if not source.exists():
                raise FileNotFoundError(f"Release input is missing: {relative}")
            copy_entry(source, stage / relative)
        bundle_manifest(stage, version=version, mode=mode, tag=tag, sha=sha)
        zip_tree(stage, destination)


def portable_python(source: Path | None, destination: Path, architecture: str, allow_placeholder: bool) -> bool:
    if source:
        source = source.resolve()
        if not source.is_file() or not tarfile.is_tarfile(source):
            raise ValueError(f"Portable Python input is not a tar archive: {source}")
        with tarfile.open(source, "r:*") as archive:
            names = archive.getnames()
            executable_headers = []
            for member in archive.getmembers():
                normalized = member.name.rstrip("/")
                if not member.isfile() or not normalized.rsplit("/", 1)[-1].startswith("python") or "/bin/" not in normalized:
                    continue
                stream = archive.extractfile(member)
                header = stream.read(20) if stream else b""
                if header.startswith(b"\x7fELF") and len(header) >= 20:
                    endian = "little" if header[5] == 1 else "big"
                    executable_headers.append(int.from_bytes(header[18:20], endian))
        if not any(name.rstrip("/").endswith(("/bin/python3", "/bin/python")) for name in names):
            raise ValueError(f"Portable Python input lacks bin/python3: {source}")
        expected_machine = {"x86_64": 62, "arm64": 183}[architecture]
        if expected_machine not in executable_headers:
            raise ValueError(
                f"Portable Python input does not contain a Linux {architecture} ELF Python executable: {source}"
            )
        shutil.copy2(source, destination)
        return True
    if not allow_placeholder:
        raise ValueError(f"A verified portable CPython input is required for Linux {architecture}")
    with tempfile.TemporaryDirectory(prefix="opencrow-python-placeholder-") as temporary:
        root = Path(temporary) / f"opencrow-python-linux-{architecture}"
        root.mkdir()
        (root / "UNRESOLVED.txt").write_text(
            "Development placeholder only. Stable release publication rejects this asset.\n",
            encoding="utf-8",
        )
        with tarfile.open(destination, "w:gz") as archive:
            archive.add(root, arcname=root.name)
    return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="2.1.0")
    parser.add_argument("--release-tag")
    parser.add_argument("--source-sha")
    parser.add_argument("--portable-python-x86", type=Path)
    parser.add_argument("--portable-python-arm64", type=Path)
    parser.add_argument("--allow-development-placeholders", action="store_true")
    parser.add_argument("--require-release-ready", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    tag = args.release_tag or args.version
    source_sha = args.source_sha or git_value("rev-parse", "HEAD", fallback="unknown")
    if DIST.exists():
        shutil.rmtree(DIST)
    if PAGES.exists():
        shutil.rmtree(PAGES)
    DIST.mkdir(parents=True)
    PAGES.mkdir(parents=True)

    common = ["README.md", "LICENSE", "skills.sh", "packages/lifecycle", "skills", "integrations", "installer"]
    full = ["README.md", "LICENSE", "install.sh", "skills.sh", "packages", "skills", "integrations", "installer", "services/constellation", "docs"]
    stage_bundle(full, DIST / "opencrow-full.zip", version=args.version, mode="full", tag=tag, sha=source_sha)
    stage_bundle(common, DIST / "opencrow-skills.zip", version=args.version, mode="skills", tag=tag, sha=source_sha)
    stage_bundle(
        ["README.md", "LICENSE", "services/constellation", "packages/lifecycle"],
        DIST / "opencrow-constellation.zip",
        version=args.version,
        mode="constellation",
        tag=tag,
        sha=source_sha,
    )

    ready_x86 = portable_python(
        args.portable_python_x86,
        DIST / "opencrow-python-linux-x86_64.tar.gz",
        "x86_64",
        args.allow_development_placeholders,
    )
    ready_arm = portable_python(
        args.portable_python_arm64,
        DIST / "opencrow-python-linux-arm64.tar.gz",
        "arm64",
        args.allow_development_placeholders,
    )
    release_ready = ready_x86 and ready_arm
    if args.require_release_ready and not release_ready:
        raise ValueError("Stable release assets require both verified portable CPython archives")

    wiki_dir = DIST / "wiki"
    build_wiki(ROOT / "docs/wiki-manifest.json", wiki_dir, args.version, tag, source_sha)
    wiki_asset = DIST / f"opencrow-wiki-{args.version}.zip"
    zip_tree(wiki_dir, wiki_asset)

    shutil.copy2(ROOT / "scripts/opencrow.sh", DIST / "install.sh")
    shutil.copy2(ROOT / "scripts/opencrow-skills.sh", DIST / "skills.sh")
    shutil.copy2(DIST / "install.sh", PAGES / "install.sh")
    shutil.copy2(DIST / "skills.sh", PAGES / "skills.sh")

    assets = []
    for path in sorted(DIST.iterdir()):
        if path.is_file() and path.name not in {"release-manifest.json", "release-checksums.txt"}:
            assets.append({"name": path.name, "sha256": sha256(path), "size": path.stat().st_size})
    manifest = {
        "schema_version": 2,
        "version": args.version,
        "release_tag": tag,
        "source_commit": source_sha,
        "built_at": utc_now(),
        "stable": "-" not in args.version,
        "release_ready": release_ready,
        "assets": assets,
        "supported": json.loads((ROOT / "installer/manifests/release.json").read_text(encoding="utf-8"))["supported"],
        "providers": json.loads((ROOT / "integrations/manifest.json").read_text(encoding="utf-8"))["providers"],
    }
    manifest_path = DIST / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    checksum_paths = [path for path in DIST.iterdir() if path.is_file() and path.name != "release-checksums.txt"]
    checksums = "".join(f"{sha256(path)}  {path.name}\n" for path in sorted(checksum_paths))
    (DIST / "release-checksums.txt").write_text(checksums, encoding="utf-8")
    shutil.copy2(manifest_path, PAGES / "release-manifest.json")
    shutil.copy2(DIST / "release-checksums.txt", PAGES / "release-checksums.txt")
    (PAGES / "_redirects").write_text("/ https://github.com/02loveslollipop/OpenCROW 302\n", encoding="utf-8")
    (PAGES / "index.html").write_text(
        '<!doctype html><meta http-equiv="refresh" content="0;url=https://github.com/02loveslollipop/OpenCROW">\n',
        encoding="utf-8",
    )
    print(f"Built {len(assets) + 2} release files for {tag}; release_ready={release_ready}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
