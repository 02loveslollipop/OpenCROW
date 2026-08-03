#!/usr/bin/env python3
"""Validate OpenCROW repository documentation and the public Wiki manifest."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from generate_wiki import build, load_manifest


ROOT = Path(__file__).resolve().parent.parent
MARKDOWN_LINK = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)\s]+)(?:\s+['\"][^'\"]*['\"])?\)")
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
)
FENCED_CODE = re.compile(r"^```([A-Za-z0-9_-]+)\s*$\n(.*?)^```\s*$", re.MULTILINE | re.DOTALL)


def anchor(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value).strip().lower()
    value = re.sub(r"[^\w\- ]", "", value, flags=re.UNICODE)
    return value.replace(" ", "-")


def headings(path: Path) -> set[str]:
    return {anchor(item) for item in HEADING.findall(path.read_text(encoding="utf-8"))}


def validate_manifest(manifest: dict[str, Any], errors: list[str]) -> None:
    slugs: set[str] = set()
    sources: set[str] = set()
    aliases: set[str] = set()
    for page in manifest["pages"]:
        required = {"title", "slug", "source", "group", "order", "redirects", "public"}
        missing = required - page.keys()
        if missing:
            errors.append(f"Wiki page is missing fields {sorted(missing)}: {page!r}")
            continue
        slug, source = page["slug"], page["source"]
        if slug in slugs:
            errors.append(f"Duplicate Wiki slug: {slug}")
        if source in sources:
            errors.append(f"Duplicate Wiki source: {source}")
        slugs.add(slug)
        sources.add(source)
        if not (ROOT / source).is_file():
            errors.append(f"Wiki source does not exist: {source}")
        for redirect in page["redirects"]:
            if redirect in slugs or redirect in aliases:
                errors.append(f"Duplicate Wiki redirect or slug: {redirect}")
            aliases.add(redirect)
    overlap = slugs & aliases
    for name in sorted(overlap):
        errors.append(f"Wiki redirect conflicts with a page slug: {name}")


def _external_link_status(target: str) -> str | None:
    headers = {"User-Agent": "OpenCROW-doc-validator/2"}
    last_error: BaseException | None = None
    for attempt in range(3):
        for method in ("HEAD", "GET"):
            try:
                request = urllib.request.Request(target, method=method, headers=headers)
                with urllib.request.urlopen(request, timeout=20) as response:
                    if response.status < 400:
                        return None
                    last_error = RuntimeError(f"HTTP {response.status}")
            except urllib.error.HTTPError as exc:
                last_error = exc
                if method == "HEAD" and exc.code in {403, 405, 501}:
                    continue
                break
            except (urllib.error.URLError, TimeoutError) as exc:
                last_error = exc
                break
        if attempt < 2:
            time.sleep(0.5 * (attempt + 1))
    return str(last_error or "unknown error")


def validate_links(
    paths: list[Path],
    errors: list[str],
    external: bool,
    external_cache: dict[str, Any] | None = None,
) -> None:
    checked_urls: set[str] = set()
    external_cache = external_cache if external_cache is not None else {}
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for _label, target in MARKDOWN_LINK.findall(text):
            if target.startswith(("mailto:", "#")):
                if target.startswith("#") and target[1:] not in headings(path):
                    errors.append(f"Missing heading anchor {target} in {path.relative_to(ROOT)}")
                continue
            if target.startswith(("https://", "http://")):
                if not target.startswith("https://"):
                    errors.append(f"External documentation link must use HTTPS: {target}")
                if external and target not in checked_urls:
                    checked_urls.add(target)
                    cached = external_cache.get(target, {})
                    checked_at = float(cached.get("checked_at", 0)) if isinstance(cached, dict) else 0
                    if time.time() - checked_at < 86_400 and cached.get("ok") is True:
                        continue
                    failure = _external_link_status(target)
                    external_cache[target] = {"ok": failure is None, "checked_at": time.time(), "error": failure}
                    if failure:
                        errors.append(f"External link failed after retries: {target}: {failure}")
                continue
            raw, separator, fragment = target.partition("#")
            destination = (path.parent / raw).resolve() if raw else path
            if not destination.exists():
                errors.append(f"Broken internal link in {path.relative_to(ROOT)}: {target}")
            elif separator and destination.is_file() and fragment not in headings(destination):
                errors.append(f"Missing target anchor in {path.relative_to(ROOT)}: {target}")


def validate_secrets(paths: list[Path], errors: list[str]) -> None:
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                errors.append(f"Possible secret in documentation: {path.relative_to(ROOT)}")


def validate_cli_help(errors: list[str]) -> None:
    commands = (
        (["bash", "installer/install.sh", "--help"], "Full OpenCROW installation"),
        (["bash", "installer/skills.sh", "--help"], "skills.sh"),
        (["python3", "installer/opencrow_manager.py", "--help"], "update"),
        (["python3", "-m", "opencrow_lifecycle.init_cli", "--help"], "antigravity"),
    )
    for command, expected in commands:
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(ROOT / "packages/lifecycle")
        result = subprocess.run(command, cwd=ROOT, env=environment, text=True, capture_output=True, check=False)
        combined = result.stdout + result.stderr
        if result.returncode or expected not in combined:
            errors.append(f"CLI help validation failed for {' '.join(command)}")


def _help_output(command: list[str]) -> str:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(ROOT / "packages/lifecycle")
    result = subprocess.run(command, cwd=ROOT, env=environment, text=True, capture_output=True, check=False)
    return result.stdout + result.stderr if result.returncode == 0 else ""


def validate_installer_examples(paths: list[Path], errors: list[str]) -> None:
    """Ensure documented OpenCROW options remain present in the matching CLI help."""

    help_cache: dict[tuple[str, ...], str] = {}
    patterns = (
        (re.compile(r"(?:^|\s)(?:sudo\s+)?bash\s+(?:\./)?install\.sh\b(.*)$"), ["bash", "installer/install.sh"]),
        (re.compile(r"(?:^|\s)(?:sudo\s+)?bash\s+(?:\./)?skills\.sh\b(.*)$"), ["bash", "installer/skills.sh"]),
        (re.compile(r"(?:^|\s)opencrow-init\b(.*)$"), ["python3", "-m", "opencrow_lifecycle.init_cli"]),
        (re.compile(r"(?:^|\s)opencrow\b(.*)$"), ["python3", "installer/opencrow_manager.py"]),
    )
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "|" in stripped:
                continue
            for pattern, base in patterns:
                match = pattern.search(stripped)
                if not match:
                    continue
                try:
                    arguments = shlex.split(match.group(1))
                except ValueError:
                    continue
                help_command = list(base)
                if base[-1].endswith("opencrow_manager.py"):
                    positionals = [value for value in arguments if not value.startswith("-")]
                    if positionals and positionals[0] in {"update", "rollback", "doctor", "integrations", "uninstall"}:
                        help_command.append(positionals[0])
                key = tuple([*help_command, "--help"])
                output = help_cache.setdefault(key, _help_output(list(key)))
                for option in (value.split("=", 1)[0] for value in arguments if value.startswith("--")):
                    if option not in output:
                        errors.append(
                            f"Documented option {option} is absent from CLI help in {path.relative_to(ROOT)}: {stripped}"
                        )
                break


def validate_code_examples(paths: list[Path], errors: list[str]) -> None:
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for language, body in FENCED_CODE.findall(text):
            language = language.lower()
            if language in {"bash", "sh", "shell"}:
                result = subprocess.run(
                    ["bash", "-n"], input=body, text=True, capture_output=True, check=False
                )
                if result.returncode:
                    errors.append(
                        f"Invalid shell example in {path.relative_to(ROOT)}: {result.stderr.strip()}"
                    )
            elif language == "json":
                try:
                    json.loads(body)
                except json.JSONDecodeError as exc:
                    errors.append(f"Invalid JSON example in {path.relative_to(ROOT)}: {exc}")
            elif language in {"python", "py"}:
                try:
                    compile(body, f"{path}:documentation-example", "exec")
                except SyntaxError as exc:
                    errors.append(f"Invalid Python example in {path.relative_to(ROOT)}: {exc}")


def validate_compatibility(errors: list[str]) -> None:
    release = json.loads((ROOT / "installer/manifests/release.json").read_text(encoding="utf-8"))
    integrations = json.loads((ROOT / "integrations/manifest.json").read_text(encoding="utf-8"))
    text = (ROOT / "docs/operator/provider-compatibility.md").read_text(encoding="utf-8").lower()
    providers = integrations.get("providers", integrations)
    names = providers.keys() if isinstance(providers, dict) else providers
    for provider in names:
        if str(provider).lower() not in text:
            errors.append(f"Compatibility table omits provider: {provider}")
    for architecture in release["supported"]["architectures"]:
        if architecture.lower() not in text:
            errors.append(f"Compatibility table omits architecture: {architecture}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-external", action="store_true")
    parser.add_argument("--external-cache", type=Path, default=ROOT / ".cache/docs-external-links.json")
    args = parser.parse_args()
    errors: list[str] = []
    manifest = load_manifest(ROOT / "docs/wiki-manifest.json")
    validate_manifest(manifest, errors)
    paths = sorted(path for path in ROOT.rglob("*.md") if not any(part in {".git", "dist"} for part in path.parts))
    external_cache: dict[str, Any] = {}
    if args.check_external and args.external_cache.is_file():
        try:
            external_cache = json.loads(args.external_cache.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            external_cache = {}
    validate_links(paths, errors, args.check_external, external_cache)
    if args.check_external:
        args.external_cache.parent.mkdir(parents=True, exist_ok=True)
        args.external_cache.write_text(json.dumps(external_cache, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    validate_secrets(paths, errors)
    validate_cli_help(errors)
    validate_installer_examples(paths, errors)
    validate_code_examples(paths, errors)
    validate_compatibility(errors)
    with tempfile.TemporaryDirectory(prefix="opencrow-wiki-") as directory:
        output = Path(directory)
        generated = build(ROOT / "docs/wiki-manifest.json", output, "2.0.0", "2.0.0", "0" * 40)
        expected = {"Home.md", "_Sidebar.md", "_Footer.md"}
        missing = expected - {path.name for path in generated}
        if missing:
            errors.append(f"Wiki generation omitted {sorted(missing)}")
        sidebar = (output / "_Sidebar.md").read_text(encoding="utf-8")
        for page in manifest["pages"]:
            if page["public"] and f"({page['slug']})" not in sidebar:
                errors.append(f"Sidebar omits public page: {page['slug']}")
    if errors:
        print("Documentation validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"Documentation validation passed ({len(paths)} Markdown files).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
