# Installation

## Skills-only product

`skills.sh` is rootless. It installs universal skills into selected detected agents, provider hook adapters, lifecycle MCP, a tiny helper environment, and `opencrow`. It never installs `opencrow-init`, Miniconda, CTF/Sage environments, domain MCP servers, OS toolboxes, Constellation, or missing agent CLIs.

```bash
bash skills.sh --agents codex,opencode --dry-run
bash skills.sh --agents codex,opencode
```

When Python supports `venv`, the installer creates a small helper. Otherwise it downloads the architecture-specific portable CPython release asset and verifies it against release checksums.

## Full product

`install.sh` supports Debian/Ubuntu (`apt`), Fedora/RHEL/Rocky (`dnf`/`yum`), and Arch (`pacman`) on Linux x86_64 and ARM64. Unsupported systems receive a compatibility report; no package commands are guessed.

```bash
bash install.sh --dry-run --yes
sudo bash install.sh
```

The full selector covers integrations, optional missing CLIs, Miniconda, headless toolbox bundles, optional SageMath, advanced manual tools, licenses, disk estimate, and the final command plan. Constellation and selected Python toolbox dependencies are installed into the OpenCROW-owned `envs/ctf` prefix, using Conda when available and a managed venv otherwise. Selecting `sagemath` creates a separate managed Conda prefix. Environment failures are reported as unresolved instead of being hidden. It exits before mutation when not elevated and prints the exact sudo rerun. User assets are written as `SUDO_USER`; only OS package operations run as root.

## Shells and offline bundles

Bash, Zsh, and Fish receive an OpenCROW-owned PATH entry. Updates accept a verified local ZIP:

```bash
opencrow update --bundle /media/opencrow-full.zip
```

Missing external packages in bundle mode are reported as unresolved rather than silently substituted.
