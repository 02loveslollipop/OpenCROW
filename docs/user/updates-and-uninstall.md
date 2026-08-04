# Updates, rollback, and uninstall

OpenCROW only applies updates through explicit commands:

```bash
opencrow update
opencrow update --version 2.1.0
opencrow update --bundle ./opencrow-full.zip
opencrow rollback
```

An update stages and verifies all managed assets, backs up provider configs, replaces same-named OpenCROW entries, applies the managed snapshot atomically, verifies integrations, and retains one previous successful snapshot. Vendor CLIs own later updates and authentication.

```bash
opencrow integrations list
opencrow integrations repair
opencrow doctor
opencrow uninstall
```

Plain uninstall removes only OpenCROW-managed files and config entries. External packages, environments, Miniconda, system packages, and vendor CLIs are retained unless their explicit purge flag is supplied:

```bash
opencrow uninstall --purge-env --purge-system --purge-agent-clis
```

Backups remain available for manual recovery unless intentionally removed.

When OpenCROW optionally installs a vendor CLI, it records the install method and bounded user-owned paths in the desired-state manifest. Claude Code and Antigravity purges remove only paths proven to have been created by that installation; provider configuration and history are preserved. If a receipt or safe vendor command is unavailable, uninstall lists the unresolved dependency, returns a failure status, and leaves it untouched.
