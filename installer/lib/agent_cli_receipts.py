#!/usr/bin/env python3
"""Capture bounded ownership receipts around optional vendor CLI installs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path


COMMANDS = {"codex": "codex", "opencode": "opencode", "claude": "claude", "antigravity": "agy"}
METHODS = {
    "codex": "npm",
    "opencode": "vendor-script",
    "claude": "vendor-script",
    "antigravity": "vendor-script",
}


def digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    value = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                value.update(chunk)
    except OSError:
        return None
    return value.hexdigest()


def candidates(home: Path, provider: str) -> list[Path]:
    command = COMMANDS[provider]
    resolved = shutil.which(command)
    paths: list[Path] = []
    if resolved:
        executable = Path(resolved).absolute()
        paths.extend([executable, executable.resolve()])
    known = {
        "codex": [home / ".local/bin/codex", home / ".local/lib/node_modules/@openai/codex"],
        "opencode": [home / ".local/bin/opencode", home / ".opencode/bin/opencode"],
        "claude": [home / ".local/bin/claude", home / ".local/share/claude"],
        "antigravity": [home / ".local/bin/agy"],
    }
    paths.extend(known[provider])
    return list(dict.fromkeys(path for path in paths if path == home or home in path.parents))


def snapshot(home: Path, providers: list[str]) -> dict[str, object]:
    result: dict[str, object] = {}
    for provider in providers:
        entries = []
        for path in candidates(home, provider):
            entries.append(
                {
                    "path": str(path),
                    "exists": path.exists() or path.is_symlink(),
                    "kind": "symlink" if path.is_symlink() else "directory" if path.is_dir() else "file",
                    "sha256": digest(path),
                }
            )
        result[provider] = {"command": COMMANDS[provider], "paths": entries}
    return result


def receipts(home: Path, providers: list[str], before: dict[str, object]) -> dict[str, object]:
    after = snapshot(home, providers)
    result: dict[str, object] = {}
    for provider in providers:
        prior = before.get(provider, {}) if isinstance(before, dict) else {}
        prior_items = prior.get("paths", []) if isinstance(prior, dict) else []
        prior_paths = {
            str(item.get("path")): bool(item.get("exists"))
            for item in prior_items
            if isinstance(item, dict)
        }
        current = after.get(provider, {})
        owned = []
        for item in current.get("paths", []) if isinstance(current, dict) else []:
            if not isinstance(item, dict) or not item.get("exists"):
                continue
            path = str(item.get("path"))
            if not prior_paths.get(path, False):
                owned.append(item)
        result[provider] = {
            "method": METHODS[provider],
            "command": COMMANDS[provider],
            "preexisting_command": any(prior_paths.values()),
            "owned_paths": owned,
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("snapshot", "receipts"))
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--providers", default="")
    parser.add_argument("--before", default="{}")
    args = parser.parse_args()
    providers = [value for value in args.providers.split(",") if value in COMMANDS]
    if args.action == "snapshot":
        value = snapshot(args.home.resolve(), providers)
    else:
        value = receipts(args.home.resolve(), providers, json.loads(args.before))
    print(json.dumps(value, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
