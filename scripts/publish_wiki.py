#!/usr/bin/env python3
"""Atomically replace a generated Wiki tree through one Git ref update."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


class WikiPublishError(RuntimeError):
    pass


def run(arguments: list[str], *, cwd: Path, capture: bool = False) -> str:
    result = subprocess.run(arguments, cwd=cwd, text=True, capture_output=capture, check=False)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip() if capture else ""
        raise WikiPublishError(f"Command failed: {' '.join(arguments)}: {detail}")
    return result.stdout.strip() if capture else ""


def publish(
    generated: Path,
    repository: str,
    *,
    version: str,
    source_sha: str,
    branch: str = "master",
    inject_failure: str | None = None,
) -> dict[str, object]:
    generated = generated.resolve()
    if not generated.is_dir() or not (generated / "Home.md").is_file():
        raise WikiPublishError(f"Generated Wiki tree is invalid: {generated}")
    with tempfile.TemporaryDirectory(prefix="opencrow-wiki-publish-") as temporary:
        checkout = Path(temporary) / "wiki"
        result = subprocess.run(
            ["git", "clone", "--branch", branch, "--single-branch", repository, str(checkout)],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            raise WikiPublishError(f"Wiki clone failed: {(result.stderr or result.stdout).strip()}")
        for child in checkout.iterdir():
            if child.name == ".git":
                continue
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
        for source in generated.iterdir():
            destination = checkout / source.name
            if source.is_dir():
                shutil.copytree(source, destination)
            else:
                shutil.copy2(source, destination)
        run(["git", "config", "user.name", "opencrow-release-bot"], cwd=checkout)
        run(
            ["git", "config", "user.email", "opencrow-release-bot@users.noreply.github.com"],
            cwd=checkout,
        )
        run(["git", "add", "--all"], cwd=checkout)
        changed = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=checkout, check=False).returncode != 0
        if not changed:
            return {"ok": True, "changed": False, "commit": run(["git", "rev-parse", "HEAD"], cwd=checkout, capture=True)}
        run(["git", "commit", "-m", f"OpenCROW {version} ({source_sha})"], cwd=checkout)
        commit = run(["git", "rev-parse", "HEAD"], cwd=checkout, capture=True)
        if inject_failure == "before-push":
            raise WikiPublishError("Injected failure before atomic Wiki ref update.")
        run(["git", "push", "origin", f"HEAD:{branch}"], cwd=checkout)
        return {"ok": True, "changed": True, "commit": commit}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generated", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--branch", default="master")
    parser.add_argument("--inject-failure", choices=("before-push",), help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        result = publish(
            args.generated,
            args.repository,
            version=args.version,
            source_sha=args.source_sha,
            branch=args.branch,
            inject_failure=args.inject_failure,
        )
    except WikiPublishError as exc:
        print(f"publish_wiki: {exc}")
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
