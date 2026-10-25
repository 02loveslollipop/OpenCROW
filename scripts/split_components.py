#!/usr/bin/env python3
"""Build paired vendoring revisions; publish them only after release validation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = {"skills": ("skills", "skills-subtree/release"), "mcp": ("packages/mcp", "mcp-subtree/release")}


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def build(source: str) -> dict:
    source = git("rev-parse", "--verify", source + "^{commit}")
    return {"schema_version": 1, "source_commit": source, "components": {
        name: {"prefix": prefix, "branch": branch, "commit": git("subtree", "split", "--quiet", "--prefix=" + prefix, source)}
        for name, (prefix, branch) in COMPONENTS.items()
    }}


def publish(manifest: dict, remote: str) -> None:
    if manifest.get("schema_version") != 1 or set(manifest["components"]) != set(COMPONENTS):
        raise ValueError("Expected paired skills and MCP component revisions")
    specs = []
    for name, (prefix, branch) in COMPONENTS.items():
        component = manifest["components"][name]
        if (component["prefix"], component["branch"]) != (prefix, branch):
            raise ValueError("Component prefix/branch mismatch")
        commit = git("rev-parse", "--verify", component["commit"] + "^{commit}")
        if git("rev-parse", commit + "^{tree}") != git("rev-parse", manifest["source_commit"] + ":" + prefix):
            raise ValueError("Component tree does not match the recorded source")
        specs.append(commit + ":refs/heads/" + branch)
    # Never overwrite a diverged branch or publish only one half of the pair.
    subprocess.run(["git", "push", "--atomic", remote, *specs], cwd=ROOT, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    create = sub.add_parser("build")
    create.add_argument("--source", default="HEAD")
    create.add_argument("--output", type=Path, required=True)
    push = sub.add_parser("publish")
    push.add_argument("--manifest", type=Path, required=True)
    push.add_argument("--remote", default="origin")
    args = parser.parse_args()
    if args.action == "build":
        args.output.write_text(json.dumps(build(args.source), indent=2) + "\n")
    else:
        publish(json.loads(args.manifest.read_text()), args.remote)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
