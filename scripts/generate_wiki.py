#!/usr/bin/env python3
"""Generate the immutable public GitHub Wiki tree from repository Markdown."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = ROOT / "docs" / "wiki-manifest.json"
GENERATED_WARNING = (
    "> **Generated documentation.** Direct Wiki edits are unsupported and will be "
    "overwritten by the next stable release publication."
)


def git_value(*arguments: str, fallback: str) -> str:
    try:
        value = subprocess.check_output(
            ["git", *arguments], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return fallback
    return value or fallback


def load_manifest(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("pages"), list):
        raise ValueError("Wiki manifest must contain a pages array")
    return value


def metadata(version: str, tag: str, sha: str, source: str) -> str:
    repository_url = f"https://github.com/02loveslollipop/OpenCROW/blob/{tag}/{source}"
    return (
        f"<!-- opencrow-wiki version={version} tag={tag} commit={sha} -->\n\n"
        f"{GENERATED_WARNING}\n\n"
        f"OpenCROW **{version}** · release `{tag}` · source commit `{sha}` · "
        f"[authoritative repository source]({repository_url})\n\n"
        "The Wiki is immutable between stable release workflows.\n\n---\n\n"
    )


def rewrite_links(text: str, source: Path, pages: list[dict[str, Any]]) -> str:
    source_to_slug = {
        (ROOT / page["source"]).resolve(): page["slug"]
        for page in pages
        if page.get("public")
    }

    def replace(match: re.Match[str]) -> str:
        label, target = match.group(1), match.group(2)
        if target.startswith(("http://", "https://", "mailto:", "#", "/")):
            return match.group(0)
        raw_path, separator, fragment = target.partition("#")
        candidate = (source.parent / raw_path).resolve()
        slug = source_to_slug.get(candidate)
        if not slug:
            return match.group(0)
        suffix = f"#{fragment}" if separator else ""
        return f"[{label}]({slug}{suffix})"

    return re.sub(r"(?<!!)\[([^\]]+)\]\(([^)]+)\)", replace, text)


def build(manifest_path: Path, output: Path, version: str, tag: str, sha: str) -> list[Path]:
    manifest = load_manifest(manifest_path)
    pages = sorted(
        (page for page in manifest["pages"] if page.get("public")),
        key=lambda page: (int(page["order"]), page["title"]),
    )
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    generated: list[Path] = []
    for page in pages:
        source = (ROOT / page["source"]).resolve()
        body = rewrite_links(source.read_text(encoding="utf-8"), source, pages)
        destination = output / f"{page['slug']}.md"
        destination.write_text(metadata(version, tag, sha, page["source"]) + body.rstrip() + "\n", encoding="utf-8")
        generated.append(destination)
        for redirect in page.get("redirects", []):
            redirect_path = output / f"{redirect}.md"
            redirect_body = (
                metadata(version, tag, sha, page["source"])
                + f"# This page moved\n\nContinue to [{page['title']}]({page['slug']}).\n"
            )
            redirect_path.write_text(redirect_body, encoding="utf-8")
            generated.append(redirect_path)

    sidebar_lines = [metadata(version, tag, sha, "docs/wiki-manifest.json"), "# OpenCROW\n"]
    group = None
    for page in pages:
        if page["group"] != group:
            group = page["group"]
            sidebar_lines.append(f"\n**{group}**\n")
        sidebar_lines.append(f"- [{page['title']}]({page['slug']})\n")
    sidebar = output / "_Sidebar.md"
    sidebar.write_text("".join(sidebar_lines), encoding="utf-8")
    generated.append(sidebar)

    footer = output / "_Footer.md"
    footer.write_text(
        metadata(version, tag, sha, "docs/wiki-manifest.json")
        + f"OpenCROW {version} · generated from `{sha}` · [source repository](https://github.com/02loveslollipop/OpenCROW/tree/{tag})\n",
        encoding="utf-8",
    )
    generated.append(footer)
    return generated


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "wiki")
    parser.add_argument("--version", default="2.0.0")
    parser.add_argument("--release-tag")
    parser.add_argument("--source-sha")
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    tag = arguments.release_tag or git_value("describe", "--tags", "--exact-match", fallback=arguments.version)
    sha = arguments.source_sha or git_value("rev-parse", "HEAD", fallback="unknown")
    generated = build(arguments.manifest.resolve(), arguments.output.resolve(), arguments.version, tag, sha)
    print(f"Generated {len(generated)} Wiki files in {arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
