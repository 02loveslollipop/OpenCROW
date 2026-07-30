SHELL := /bin/bash

ENV ?= ctf

.PHONY: help install dry-run update verify uninstall smoke sync-skills remove-skills test e2e build-releases

help:
	@echo "OpenCROW Monorepo Targets:"
	@echo "  make build-releases    Build opencrow-cli.zip and opencrow-constellation.zip into dist/"
	@echo "  make install ENV=ctf   Run CLI installer"
	@echo "  make dry-run ENV=ctf   Run CLI installer in dry-run mode"
	@echo "  make update ENV=ctf    Run additive update"
	@echo "  make verify ENV=ctf    Verify CLI installation"
	@echo "  make uninstall ENV=ctf Uninstall CLI"
	@echo "  make smoke             Run smoke checks on all services"
	@echo "  make test              Run unit tests across services"
	@echo "  make e2e               Run lightweight E2E installation test"

e2e:
	bash scripts/test_installation_e2e.sh

build-releases:
	python3 scripts/build_releases.py

install:
	bash services/opencrow-cli/scripts/install.sh --env "$(ENV)"

dry-run:
	bash services/opencrow-cli/scripts/install_headless.sh --env "$(ENV)" --dry-run

update:
	bash services/opencrow-cli/scripts/update_headless.sh --env "$(ENV)" --all-toolboxes --profile headless

verify:
	bash services/opencrow-cli/scripts/verify.sh --env "$(ENV)"

uninstall:
	bash services/opencrow-cli/scripts/uninstall.sh --env "$(ENV)"

sync-skills:
	bash services/opencrow-cli/scripts/sync_skills.sh

remove-skills:
	bash services/opencrow-cli/scripts/remove_skills.sh

smoke:
	bash -n scripts/opencrow.sh
	bash -n scripts/test_installation_e2e.sh
	bash -n services/opencrow-cli/scripts/_installer_bootstrap.sh
	bash -n services/opencrow-cli/scripts/install.sh
	bash -n services/opencrow-cli/scripts/install_headless.sh
	bash -n services/opencrow-cli/scripts/update_headless.sh
	bash -n services/opencrow-cli/scripts/verify.sh
	bash -n services/opencrow-cli/scripts/uninstall.sh
	bash -n services/opencrow-cli/scripts/sync_skills.sh
	bash -n services/opencrow-cli/scripts/sync_gemini_mcp_config.sh
	bash -n services/opencrow-cli/scripts/remove_skills.sh
	bash -n services/opencrow-cli/bin/opencrow-stego-mcp
	bash -n services/opencrow-cli/bin/opencrow-forensics-mcp
	bash -n services/opencrow-cli/bin/opencrow-osint-mcp
	bash -n services/opencrow-cli/bin/opencrow-web-mcp
	bash -n services/opencrow-cli/bin/opencrow-crypto-mcp
	bash -n services/opencrow-cli/bin/opencrow-pwn-mcp
	bash -n services/opencrow-cli/bin/opencrow-reversing-mcp
	bash -n services/opencrow-cli/bin/opencrow-network-mcp
	bash -n services/opencrow-cli/bin/opencrow-utility-mcp
	bash -n services/opencrow-cli/bin/opencrow-netcat-mcp
	bash -n services/opencrow-cli/bin/opencrow-ssh-mcp
	bash -n services/opencrow-cli/bin/opencrow-minecraft-mcp
	bash -n services/opencrow-cli/bin/opencrow-constellation-client
	bash -n services/opencrow-cli/bin/opencrow-constellation-mcp
	bash -n services/opencrow-cli/bin/opencrow-constellation-join
	bash -n services/opencrow-cli/bin/opencrow-constellation-admin
	bash -n services/opencrow-cli/bin/opencrow-constellation-join.bash-completion
	bash -n services/opencrow-cli/bin/opencrow-constellation-admin.bash-completion
	python3 -m py_compile scripts/build_releases.py
	python3 -m py_compile services/opencrow-cli/scripts/tool_catalog.py
	python3 -m py_compile services/opencrow-cli/scripts/install_cli.py
	python3 -m py_compile services/opencrow-cli/scripts/check_mcp_server.py
	python3 -m py_compile services/opencrow-cli/scripts/opencrow_mcp_core.py
	python3 -m py_compile services/opencrow-cli/scripts/opencrow_ctf_mcp_common.py
	python3 -m py_compile services/opencrow-cli/scripts/opencrow_io_mcp_common.py
	python3 -m py_compile services/opencrow-cli/scripts/opencrow_crypto_mcp.py
	python3 -m py_compile services/opencrow-cli/scripts/opencrow_pwn_mcp.py
	python3 -m py_compile services/opencrow-cli/scripts/opencrow_reversing_mcp.py
	python3 -m py_compile services/opencrow-cli/scripts/opencrow_reversing_worker.py
	PYTHONPATH=services/opencrow-cli/scripts python3 -m unittest services/opencrow-cli/tests/test_opencrow_reversing_worker.py
	python3 -m py_compile services/opencrow-cli/scripts/reversing_mcp_smoke.py
	python3 -m py_compile services/opencrow-cli/scripts/stego_mcp_smoke.py
	python3 -m py_compile services/opencrow-cli/scripts/opencrow_network_mcp.py
	python3 -m py_compile services/opencrow-cli/scripts/opencrow_utility_mcp.py
	python3 -m py_compile services/opencrow-cli/scripts/opencrow_stego_mcp.py
	PYTHONPATH=services/opencrow-cli/scripts python3 services/opencrow-cli/tests/test_opencrow_stego_mcp.py
	python3 -m py_compile services/opencrow-cli/scripts/opencrow_forensics_mcp.py
	python3 -m py_compile services/opencrow-cli/scripts/opencrow_osint_mcp.py
	python3 -m py_compile services/opencrow-cli/scripts/opencrow_web_mcp.py
	python3 -m py_compile services/opencrow-cli/scripts/opencrow_netcat_mcp.py
	python3 -m py_compile services/opencrow-cli/scripts/opencrow_ssh_mcp.py
	python3 -m py_compile services/opencrow-cli/scripts/opencrow_minecraft_mcp.py
	python3 -m py_compile services/opencrow-cli/scripts/opencrow_constellation_join.py
	python3 -m py_compile services/opencrow-cli/scripts/opencrow_constellation_admin.py
	python3 -m py_compile services/opencrow-cli/scripts/opencrow_constellation_watcher.py
	python3 -m py_compile services/opencrow-cli/scripts/opencrow_constellation_mcp.py
	python3 -m py_compile services/constellation/constellation/__init__.py
	python3 -m py_compile services/constellation/constellation/config.py
	python3 -m py_compile services/constellation/constellation/workspace.py
	python3 -m py_compile services/constellation/constellation/prompts.py
	python3 -m py_compile services/constellation/constellation/client.py
	python3 -m py_compile services/constellation/constellation/storage.py
	python3 -m py_compile services/constellation/constellation/backend.py
	python3 -m py_compile services/constellation/constellation/ui.py
	python3 -m py_compile services/constellation/constellation/watcher.py
	bash services/opencrow-cli/scripts/install_headless.sh --env "$(ENV)" --dry-run

test:
	PYTHONPATH=services/opencrow-cli/scripts:services/constellation pytest services/opencrow-cli/tests/ services/constellation/tests/
