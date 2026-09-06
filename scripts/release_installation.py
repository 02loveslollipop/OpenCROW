#!/usr/bin/env python3
"""Release-only bundle preparation and installation/startup assertions (no agent turns)."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import shutil
import subprocess
import zipfile

PROVIDERS = {"codex", "opencode", "claude", "antigravity"}
TOOLBOXES = {"utility", "network", "reversing", "pwn", "web", "forensics", "stego", "crypto", "osint"}


def read_json(path: Path):
    return json.loads(path.read_text())


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def previous_release(releases, candidate: str) -> str:
    eligible = [r for r in releases if not r["isDraft"] and not r["isPrerelease"]
                and r["tagName"] != candidate
                and re.fullmatch(r"\d+\.\d+\.\d+(?:\+[0-9A-Za-z.-]+)?", r["tagName"])]
    require(eligible, "No previous published stable release; an upgrade baseline is required")
    return max(eligible, key=lambda r: r["publishedAt"])["tagName"]


def extract_bundle(bundle: Path, destination: Path):
    require(not destination.exists(), f"Extraction destination already exists: {destination}")
    with zipfile.ZipFile(bundle) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        require(len(names) == len(set(names)), "Duplicate archive paths")
        for entry in entries:
            path = PurePosixPath(entry.filename)
            require(not path.is_absolute() and ".." not in path.parts and "\\" not in entry.filename,
                    f"Unsafe archive path: {entry.filename}")
            require(not stat.S_ISLNK(entry.external_attr >> 16), "Archive symlinks are unsupported")
        checksums = json.loads(archive.read("checksums.json"))
        files = {e.filename for e in entries if not e.is_dir()} - {"checksums.json"}
        require(set(checksums) == files, "Bundle checksum inventory is incomplete")
        for name, expected in checksums.items():
            require(hashlib.sha256(archive.read(name)).hexdigest() == expected, f"Bundle checksum mismatch: {name}")
        manifest = json.loads(archive.read("release-manifest.json"))
        require(manifest.get("schema_version") == 2 and manifest.get("install_mode") == "full", "Expected a full release bundle")
        require("installer/install.sh" in files, "Bundle installer missing")
        archive.extractall(destination)
        for entry in entries:
            if not entry.is_dir():
                (destination / entry.filename).chmod((entry.external_attr >> 16) & 0o777 or 0o644)
    return manifest


def fetch_previous(candidate: str, destination: Path):
    releases = json.loads(subprocess.check_output(
        ["gh", "release", "list", "--limit", "1000", "--json", "tagName,isDraft,isPrerelease,publishedAt"], text=True))
    tag = previous_release(releases, candidate)
    destination.mkdir(parents=True, exist_ok=False)
    subprocess.run(["gh", "release", "download", tag, "--dir", str(destination),
                    "--pattern", "opencrow-full.zip", "--pattern", "release-checksums.txt"], check=True)
    hashes = dict((line.split()[1].lstrip("*"), line.split()[0])
                  for line in (destination / "release-checksums.txt").read_text().splitlines() if line.strip())
    require(digest(destination / "opencrow-full.zip") == hashes.get("opencrow-full.zip"), "Published bundle checksum mismatch")
    manifest = extract_bundle(destination / "opencrow-full.zip", destination / "verified")
    require(manifest.get("release_tag") == tag, "Published bundle tag mismatch")
    (destination / "baseline.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Upgrade baseline: {tag}")


def run(command, report: Path, name: str, input_text=None):
    # Commands run only in the disposable user's clean HOME, with no host credentials.
    with (report / f"{name}.stderr.log").open("w") as err, (report / f"{name}.stdout.log").open("w") as out:
        result = subprocess.run(command, input=input_text, text=True, stdout=out, stderr=err, timeout=120)
    require(result.returncode == 0, f"{name} exited {result.returncode}; see phase logs")
    return (report / f"{name}.stdout.log").read_text()


def verify_snapshot(source: Path, snapshot: Path):
    checksums = read_json(source / "checksums.json")
    prefixes = ("packages/lifecycle/", "packages/mcp/", "services/constellation/", "skills/", "integrations/")
    for name, expected in checksums.items():
        if name.startswith(prefixes) or name == "installer/opencrow_manager.py":
            target = snapshot / name
            require(target.is_file() and digest(target) == expected, f"Installed asset differs from bundle: {name}")


def verify(source: Path, report: Path, baseline: Path | None):
    report.mkdir(parents=True, exist_ok=True)
    home = Path.home()
    data = home / ".local/share/opencrow"
    state = read_json(home / ".local/state/opencrow/state.json")
    manifest = read_json(source / "release-manifest.json")
    version = manifest["version"].split("+")[0]
    require(state.get("install_mode") == "full", "Install is not full")
    require(state.get("version") == version, "Installed version differs from release")
    require(set(state.get("selected_agents", [])) == PROVIDERS, "Not all providers installed")
    require(set(state.get("selected_toolboxes", [])) == TOOLBOXES, "Not all default toolboxes installed")
    verify_snapshot(source, data / "current")
    if baseline:
        require(manifest["release_tag"] != read_json(baseline / "release-manifest.json")["release_tag"], "Upgrade baseline must be a different release")
        previous = read_json(home / ".local/state/opencrow/previous-state.json")
        require(previous["selected_agents"] == state["selected_agents"] and previous["selected_toolboxes"] == state["selected_toolboxes"], "Update changed selections")
        verify_snapshot(baseline, data / "previous")
        require((home / "release-user-data.txt").read_text() == "preserve me\n", "Update lost user data")
        require("# release-user-config: preserve me" in (home / ".codex/config.toml").read_text(), "Update lost user configuration")
    for utility in ("jq", "xxd", "tmux", "screen", "rg", "fzf"):
        require(shutil.which(utility), f"Core utility missing: {utility}")
    methods = state.get("package_methods", {})
    environments = methods.get("python_environments", {})
    require("ctf" in environments.get("installed", []), "Managed CTF environment was not installed")
    require(not environments.get("unresolved"), "Unresolved Python dependencies; see installation log")
    runtime = data / "envs/ctf/bin/python"
    require(runtime.is_file(), "Managed Python missing")
    run([str(runtime), "-m", "pip", "check"], report, "python-dependencies")
    doctor = json.loads(run(["opencrow", "doctor"], report, "doctor"))
    require(doctor.get("ok") and doctor.get("mode") == "full" and doctor.get("version") == version, "Doctor failed")
    integrations = {item["provider"]: item for item in doctor["integrations"] if item["selected"]}
    require(set(integrations) == PROVIDERS and all(i["healthy"] for i in integrations.values()), "Provider integration unhealthy")
    providers = read_json(source / "integrations/manifest.json")["providers"]
    for provider, config in providers.items():
        for skill in (source / "skills").glob("*/SKILL.md"):
            target = home / config["skills_dir"] / skill.parent.name / "SKILL.md"
            require(target.is_file() and digest(target) == digest(skill), f"Missing/changed {provider} skill: {skill.parent.name}")
    for cli in ("codex", "opencode", "claude", "agy"):
        require(run([cli, "--version"], report, f"{cli}-version").strip(), f"Empty {cli} version")
        run([cli, "--help"], report, f"{cli}-help")
    for cli, args in (("codex", ["mcp", "list", "--json"]), ("opencode", ["debug", "config"]),
                      ("claude", ["mcp", "list"]), ("agy", ["mcp", "list"])):
        run([cli, *args], report, f"{cli}-config")
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "release-install-check", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    servers = ["opencrow-lifecycle-mcp"] + sorted(
        path.stem.replace("_", "-") for path in (source / "packages/mcp/servers").glob("opencrow_*_mcp.py"))
    for server in servers:
        output = run([server], report, f"{server}-startup", "\n".join(map(json.dumps, requests)) + "\n")
        responses = {item["id"]: item for line in output.splitlines() if (item := json.loads(line)).get("id")}
        info = responses.get(1, {}).get("result", {}).get("serverInfo", {})
        require(info.get("name") and info.get("version"), f"{server} initialize failed")
        if server == "opencrow-lifecycle-mcp":
            require(info["version"] == version, "Lifecycle MCP version mismatch")
        require(responses.get(2, {}).get("result", {}).get("tools"), f"{server} tool registration failed")
    (report / "summary.json").write_text(json.dumps({"ok": True, "release": manifest, "upgrade": baseline is not None,
        "doctor": doctor, "package_methods": methods}, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch-previous")
    fetch.add_argument("candidate")
    fetch.add_argument("destination", type=Path)
    extract = sub.add_parser("extract")
    extract.add_argument("bundle", type=Path)
    extract.add_argument("destination", type=Path)
    check = sub.add_parser("verify")
    check.add_argument("source", type=Path)
    check.add_argument("report", type=Path)
    check.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    if args.command == "fetch-previous":
        fetch_previous(args.candidate, args.destination)
    elif args.command == "extract":
        extract_bundle(args.bundle, args.destination)
    else:
        try:
            verify(args.source, args.report, args.baseline)
        except Exception as error:
            args.report.mkdir(parents=True, exist_ok=True)
            (args.report / "summary.json").write_text(json.dumps({"ok": False, "error": str(error)}, indent=2) + "\n")
            raise


if __name__ == "__main__":
    main()
