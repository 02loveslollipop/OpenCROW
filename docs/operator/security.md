# Security and permission behavior

Local provider sessions use native approvals by default. `--unsafe` is explicit and maps to each provider's documented bypass/auto-approval control. Lifecycle hooks probe `sudo -n true`; agents may use sudo autonomously only when that non-interactive probe succeeds.

Full installation requires sudo but divides ownership: OS package operations run as root, while provider configs, skills, environments, launchers, and shell files belong to `SUDO_USER`. Skills-only installation is rootless.

Provider config files are backed up before same-named integration entries are replaced. Deselecting a provider removes only OpenCROW-managed skills and entries. Updates verify checksums before mutation and preserve one rollback snapshot.

The reverse-shell async skill is a listener/session manager for authorized CTF, lab, and owned-system use; it does not generate callback payloads. Its `rsx` helper defaults to loopback, requires explicit `--allow-remote` consent for any non-loopback bind, and supports an expected peer IP or CIDR. Runtime hosts remain responsible for firewall policy and network exposure.

Hooks block obvious target-specific writeup, solution, flag, and walkthrough searches while permitting software documentation, algorithm, optimization, mathematics, and research sources. Hook failures fail open and leave a diagnostic log; user interruption and provider/authentication failures are never blocked.

Constellation runtime hosts are explicitly trusted full-auto machines. Do not deploy them on a general workstation or with credentials unrelated to the assigned challenges.
