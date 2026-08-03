# Updates, rollback, and uninstall

OpenCROW only applies updates through explicit commands:

```bash
opencrow update
opencrow update --version 2.0.1
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
