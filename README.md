# OpenCROW

Open Codex Runtime for Offensive Workflows.

OpenCROW is an agentic AI orchestration framework for offensive security and CTF workflows. It bootstraps a local execution runtime around an existing Anaconda or Miniconda installation, syncs repo-managed Codex skills into `~/.codex/skills`, installs the underlying execution stack those agents need, and exposes provider-neutral stdio MCP servers so agents can work through typed interfaces instead of ad hoc shell glue.

The project is structured as a monorepo containing services for the CLI runtime, MCP servers, agent skills, and OpenCROW Constellation:

- `services/opencrow-cli`: Workflow entrypoints (`opencrow-autosetup`, `opencrow-exploit`), MCP servers, installer, and agent skills.
- `services/constellation`: OpenCROW Constellation backend, UI dashboard, and multi-agent coordination surface.
- `docs`: Project documentation and MCP specs.

---

## Installation via GitHub Releases

OpenCROW is distributed via GitHub Releases. End users do not need to clone the repository to install and use OpenCROW.

### 1. Installing OpenCROW CLI

To install the OpenCROW CLI, run the single-command remote installer:

```bash
curl -fsSL https://opencrow.02labs.me/release/opencrow-cli.sh | bash
```

To install a specific version release:

```bash
curl -fsSL https://opencrow.02labs.me/release/opencrow-cli.sh | bash -s -- --version v1.0.0
```

### 2. Deploying OpenCROW Constellation (Docker)

OpenCROW Constellation runs as a set of containerized services (Backend, UI, MongoDB, GridFS). To deploy Constellation:

1. Download `opencrow-constellation.zip` from the latest [GitHub Release](https://github.com/02loveslollipop/OpenCROW/releases).
2. Extract the package and start the services using Docker Compose:

```bash
unzip opencrow-constellation.zip -d opencrow-constellation
cd opencrow-constellation
docker compose up -d
```

---

## OpenCROW Monorepo Development

This repository is strictly dedicated to development, testing, and building release packages.

### Monorepo Build & Development Commands

From the repository root:

- **Build GitHub Release packages**:
  ```bash
  make build-releases
  ```
  *(Packages `dist/opencrow-cli.zip` and `dist/opencrow-constellation.zip`)*

- **Run smoke verification**:
  ```bash
  make smoke
  ```

- **Run unit test suite**:
  ```bash
  make test
  ```

- **Run local CLI installation dry-run**:
  ```bash
  make dry-run
  ```

---

## Requirements

- An existing Anaconda or Miniconda installation
- Ubuntu or another Debian-like system with `apt-get`
- `sudo` access for system package installation
- Network access

If Conda is missing, the installer stops and prints official download links:

- Miniconda: <https://docs.conda.io/en/latest/miniconda.html>
- Anaconda: <https://www.anaconda.com/download>

---

## Architecture & Documentation

- [docs/MCP_ARCHITECTURE.md](docs/MCP_ARCHITECTURE.md) - Standard specification for OpenCROW stdio MCP servers.
- [docs/RUNTIME_DASHBOARD.md](docs/RUNTIME_DASHBOARD.md) - Dashboard interface reference.
- [services/constellation/README.md](services/constellation/README.md) - OpenCROW Constellation setup guide.
