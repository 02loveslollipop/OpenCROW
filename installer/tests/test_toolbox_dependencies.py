"""Keep advertised toolbox capabilities tied to provisioning or manual status."""
from __future__ import annotations

import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
# Commands/imports whose distribution name differs, or is supplied by a package.
PROVIDERS = {
    "z3": "z3-solver", "sherlock": "sherlock-project", "claripy": "angr",
    "checksec": "pwntools", "nc": "netcat-openbsd", "objdump": "binutils",
    "ghidra-headless": "ghidra-gui", "rg": "ripgrep",
}


def advertised_missing(root: Path) -> list[str]:
    envs = json.loads((root / "installer/manifests/python-environments.json").read_text())
    components = json.loads((root / "installer/manifests/components.json").read_text())
    platforms = json.loads((root / "installer/platforms/packages.json").read_text())["platforms"]
    missing = []
    for skill in sorted((root / "skills").glob("opencrow-*-toolbox/SKILL.md")):
        toolbox = skill.parent.name.removeprefix("opencrow-").removesuffix("-toolbox")
        provided = set(envs["ctf"]["toolboxes"].get(toolbox, [])) | set(components["manual_tools"])
        for platform in platforms.values():
            provided.update(platform.get(toolbox, []))
        # Frontmatter descriptions are the advertised tool catalog, unlike the
        # body which also quotes operation names, env names and example inputs.
        description = skill.read_text().split("---", 2)[1]
        for name in re.findall(r"`([^`]+)`", description):
            if name == "ctf":
                assert envs["ctf"]["python"]
            elif PROVIDERS.get(name, name) not in provided:
                missing.append(f"{toolbox}: {name}")
    return missing


def test_advertised_toolbox_dependencies_have_providers():
    assert advertised_missing(ROOT) == []


def test_missing_new_skill_tool_is_detected(tmp_path):
    import shutil
    shutil.copytree(ROOT / "installer/manifests", tmp_path / "installer/manifests")
    shutil.copytree(ROOT / "installer/platforms", tmp_path / "installer/platforms")
    skill = tmp_path / "skills/opencrow-osint-toolbox/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text('---\nname: opencrow-osint-toolbox\ndescription: Use `unprovisioned-tool`.\n---\n')
    assert advertised_missing(tmp_path) == ["osint: unprovisioned-tool"]


def test_new_python_capabilities_are_in_the_correct_selected_environment():
    envs = json.loads((ROOT / "installer/manifests/python-environments.json").read_text())
    assert {"sherlock-project", "waybackpy", "shodan"} <= set(envs["ctf"]["toolboxes"]["osint"])
    assert {"cysignals", "fpylll"} <= set(envs["ctf"]["toolboxes"]["crypto"])
    components = json.loads((ROOT / "installer/manifests/components.json").read_text())
    for name in ("zsteg", "pwndbg", "pwninit"):
        assert name in components["manual_tools"]
        assert components["manual_tool_notes"][name]


def test_launcher_exposes_managed_python_console_scripts(tmp_path):
    import os
    import subprocess
    import sys
    from opencrow_manager import Paths, StateEngine
    paths = Paths(home=tmp_path, data=tmp_path / "data", state=tmp_path / "state", bin=tmp_path / "bin")
    runtime = paths.data / "envs/ctf/bin"
    runtime.mkdir(parents=True)
    (runtime / "python").symlink_to(sys.executable)
    (runtime / "sherlock").write_text("#!/bin/sh\nexit 0\n")
    (runtime / "sherlock").chmod(0o755)
    script = tmp_path / "probe.py"
    script.write_text("import shutil; print(shutil.which('sherlock'))\n")
    StateEngine(paths)._write_launcher("probe", str(script), [])
    env = {k: v for k, v in os.environ.items() if k != "OPENCROW_PYTHON"}
    env["PATH"] = "/usr/bin:/bin"
    result = subprocess.run([str(paths.bin / "probe")], env=env, text=True, capture_output=True, check=True)
    assert result.stdout.strip() == str(runtime / "sherlock")
