SHELL := /bin/bash

.PHONY: help install skills dry-run smoke test e2e docs wiki build-releases distro-e2e

help:
	@echo "OpenCROW v2 targets:"
	@echo "  make skills            Rootless skills-only install"
	@echo "  make install           Full interactive install (requires sudo)"
	@echo "  make dry-run           Show a full default install plan"
	@echo "  make test              Run all unit and integration tests"
	@echo "  make smoke             Validate scripts, imports, docs, and provider adapters"
	@echo "  make e2e               Exercise skills install/update/rollback/uninstall in isolation"
	@echo "  make wiki              Generate the public Wiki tree"
	@echo "  make build-releases    Build development release assets"
	@echo "  make distro-e2e        Run actual installs in disposable distro containers"

skills:
	bash installer/skills.sh

install:
	sudo bash installer/install.sh

dry-run:
	bash installer/install.sh --agents codex --toolboxes utility,network,reversing,pwn,web,forensics,stego,crypto,osint --yes --dry-run

docs:
	python3 scripts/validate_docs.py

wiki:
	python3 scripts/generate_wiki.py

build-releases:
	python3 scripts/build_releases.py --allow-development-placeholders

e2e:
	bash scripts/test_installation_e2e.sh

distro-e2e:
	bash scripts/test_distro_matrix.sh

smoke:
	bash -n install.sh skills.sh installer/install.sh installer/skills.sh installer/lib/*.sh scripts/*.sh
	python3 -m py_compile installer/opencrow_manager.py installer/lib/*.py scripts/*.py packages/lifecycle/opencrow_lifecycle/*.py packages/mcp/core/*.py packages/mcp/servers/*.py skills/*/scripts/*.py services/constellation/constellation/*.py
	python3 scripts/validate_docs.py
	PYTHONPATH=packages/lifecycle python3 -m opencrow_lifecycle.init_cli codex --challenge-file README.md --dry-run >/dev/null
	bash installer/install.sh --agents codex --toolboxes utility --no-miniconda --yes --dry-run >/dev/null

test:
	PYTHONPATH=installer:packages/lifecycle:packages/mcp/core:packages/mcp/servers:services/constellation:. pytest -q packages/lifecycle/tests packages/mcp/tests installer/tests services/constellation/tests tests
