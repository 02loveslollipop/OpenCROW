# Quick start

Choose the small package if agents are already installed and you only want reusable skills and lifecycle enforcement:

```bash
curl -fsSL https://opencrow.02labs.me/skills.sh | bash
opencrow doctor
```

Choose the full framework for the initializer, domain MCPs, toolboxes, Miniconda option, and Constellation:

```bash
curl -fsSL https://opencrow.02labs.me/install.sh | sudo bash
opencrow doctor
```

After a full installation, save the exact organizer description and initialize one provider:

```bash
mkdir -p orbital-lock
cd orbital-lock
opencrow-init claude --challenge-file ../orbital-lock.txt
```

For a hands-on session instead of a headless run, open the provider terminal in the initialized workspace (approvals stay native):

```bash
opencrow-init opencode --interactive --challenge-file ../orbital-lock.txt
```

Local invocations complete one phase. The dashboard automatically enqueues one solving continuation after a valid reconnaissance handoff.
