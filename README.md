# OpenCROW

Open Codex Runtime for Offensive Workflows.

Bootstrap an offensive-workflow workstation around an existing Anaconda or Miniconda installation.

This setup creates or updates a `ctf` conda environment, installs the Python solver/exploit stack used in this workspace, and installs the native reversing and pwn tools that were added here.
It also vendors Codex skill folders and injects them into `~/.codex/skills`.

## Requirements

- An existing Anaconda or Miniconda installation
- Ubuntu or another Debian-like system with `apt-get`
- `sudo` access for system package installation
- Network access

If Conda is not installed, the installer now stops with official download links:

- Miniconda: <https://docs.conda.io/en/latest/miniconda.html>
- Anaconda: <https://www.anaconda.com/download>

The installer assumes:

- your user-local binaries live in `~/.local/bin`
- your optional large tools live in `~/.local/opt`
- the main working environment is named `ctf`

## What It Installs

### Python packages in `ctf`

Pinned in [requirements-ctf.txt](/home/zerotwo/ctf-toolkit-bootstrap/requirements-ctf.txt):

- `angr`
- `pwntools`
- `z3-solver`
- `claripy`
- `capstone`
- `unicorn`
- `keystone-engine`
- `ropper`
- `r2pipe`
- `lief`
- `scapy`
- `fpylll`
- supporting packages needed by this exact stack

### System packages

- `checksec`
- `gdbserver`
- `ltrace`
- `nasm`
- `patchelf`
- `python3-xlib`
- `qemu-user`
- `qemu-user-static`
- `radare2`
- `rsync`
- `unzip`
- `ruby`
- `curl`
- `git`
- `openjdk-21-jre`

### User-local tools

- `pwndbg`
- `pwninit`
- `seccomp-tools`
- `ghidra-headless`
- `ghidra`

### Codex skills injected into `~/.codex/skills`

- `opencrow-crypto-toolbox`
- `opencrow-pwn-toolbox`
- `opencrow-reversing-toolbox`
- `opencrow-network-toolbox`
- `opencrow-web-toolbox`
- `minecraft-async`
- `netcat-async`
- `sagemath`
- `ssh-async`

## Included Skills

The OpenCROW toolbox layer now splits the old broad `ctf-tools` category into narrower skills so agent routing is more precise and less context-heavy.

### `opencrow-crypto-toolbox`

Use this skill for Python-first crypto work in the `ctf` environment when Sage is unnecessary or too heavy. It covers constraint solving with `z3`, lattice work with `fpylll`, and the surrounding Python glue common in CTF crypto problems where the agent needs to parse challenge data, model unknown values, and search for solutions quickly.

It is the right default when the challenge is mostly symbolic equations, bit-vectors, key-recovery constraints, or lattice reduction expressed in ordinary Python. When the problem requires finite fields, elliptic curves, or Sage-native algebra, `sagemath` remains the better match.

Typical use cases:

- solve symbolic or bit-vector crypto challenges with `z3`
- run LLL or BKZ workflows with `fpylll`
- build small Python helpers for ciphertext, oracle, or transcript analysis

### `opencrow-pwn-toolbox`

Use this skill for exploitation-heavy workflows in the `ctf` environment. It groups the installed runtime-facing tools such as `pwntools`, `pwndbg`, `gdb`, `gdbserver`, `checksec`, `patchelf`, `pwninit`, `seccomp-tools`, `qemu-user`, `gcc`, and `nasm` into a dedicated exploit toolbox instead of mixing them with unrelated analysis tasks.

This is the right toolbox when the goal is to triage an ELF, understand mitigations, patch in the shipped loader or libc, debug a crashing primitive, or build and test an exploit script. It keeps the agent focused on the "gain control" path instead of the broader reverse-engineering or crypto stack.

Typical use cases:

- build exploit scripts with `pwntools`
- inspect mitigations with `checksec`
- debug locally with `gdb` or `pwndbg`
- patch challenge runtimes with `pwninit` or `patchelf`
- run non-native binaries through `qemu-user`

### `opencrow-reversing-toolbox`

Use this skill for binary-understanding workflows in the `ctf` environment. It collects the installed disassembly, emulation, symbolic-execution, tracing, and patching stack: `angr`, `claripy`, `capstone`, `keystone`, `unicorn`, `ropper`, `r2pipe`, `lief`, `ghidra-headless`, `radare2`, `objdump`, `strace`, `ltrace`, and `binwalk`.

This is the better fit when the task is to recover logic, inspect control flow, decompile or lift behavior, emulate instructions, or extract firmware contents. It deliberately separates "understand the binary" workflows from exploit delivery so the skill trigger is tighter and the instructions stay relevant.

Typical use cases:

- script symbolic execution or CFG recovery with `angr`
- disassemble or emulate instructions with `capstone`, `keystone`, and `unicorn`
- inspect binaries with `radare2`, `objdump`, or `ghidra-headless`
- trace runtime behavior with `strace` or `ltrace`
- extract or inspect embedded blobs with `binwalk`

### `opencrow-network-toolbox`

Use this skill for packet- and protocol-level tasks in the `ctf` environment where `scapy` is the main installed tool. It covers Python-driven packet crafting, protocol parsing, synthetic traffic generation, and PCAP inspection without conflating those workflows with persistent stream sessions.

This toolbox is intentionally narrow today because only `scapy` belongs in this category from the current installed stack. That is still useful for network challenge automation, packet decoders, and quick protocol experiments that benefit from structured packet handling.

Typical use cases:

- inspect or transform PCAPs with Python
- generate custom packets for network challenges
- write ad hoc dissectors or protocol helpers with `scapy`

### `opencrow-web-toolbox`

Use this skill only as a placeholder category for future web CTF tooling. There are no dedicated web tools mapped into the current OpenCROW workstation yet, so the skill exists to reserve the category and make the gap explicit instead of pretending the toolbox is populated.

For now it ships with a dummy tool that prints `TODO: update with real tools`. Once dedicated HTTP, browser, or web exploitation tooling is added to the workstation, this toolbox should be updated with real instructions and concrete tool mappings.

Typical use cases:

- acknowledge that web is a planned toolbox category
- provide a stable place to add real web tooling later

### `minecraft-async`

Use this skill when a challenge depends on driving a locally installed Minecraft client. It launches the existing `~/.minecraft` Java install directly, favors offline-mode identities that are common in Minecraft CTF infrastructure, and manages the running client asynchronously instead of relying on the official launcher UI.

It also exposes fast X11-backed actions for focusing the game window, sending chat, issuing slash commands, capturing screenshots, and checking Minecraft logs. That makes it useful for tasks where the agent needs both process-level control and visual state inspection, such as joining a server, entering a world, teleporting, validating on-screen state, or diagnosing disconnects and startup failures.

Typical use cases:

- launch directly into a multiplayer server or singleplayer world
- operate with alternate offline usernames
- send in-game commands quickly without manual typing
- inspect `latest.log` and capture screenshots while debugging state

### `netcat-async`

Use this skill when a target speaks a line-oriented or raw TCP protocol and the connection needs to stay open across multiple agent actions. Instead of one-shot `nc` invocations, it keeps a named session alive in the background, lets the agent send input incrementally, and preserves a read log for later inspection.

This is useful for interactive CTF services, menu-driven binaries behind `socat`, custom challenge daemons, or any network flow where reads and writes happen at different times. The session model is intentionally simple: start, send, read, inspect status, and stop.

Typical use cases:

- interact with a remote challenge service over TCP
- keep a connection open while exploring protocol behavior
- capture and tail responses without losing session state
- avoid repeatedly reconnecting while testing payloads

### `sagemath`

Use this skill for math-heavy or algebra-heavy tasks that need real Sage instead of plain Python. It is intended for cryptography and CTF problem classes where finite fields, elliptic curves, modular arithmetic, lattices, polynomial algebra, small-root attacks, or PRNG analysis are easier or only practical in SageMath.

The skill complements `opencrow-crypto-toolbox` rather than replacing it. If the work is ordinary Python scripting, solver glue, or lattice code that fits `fpylll`, the crypto toolbox is the better default. If the work depends on Sage objects, symbolic number theory, lattice reduction patterns, or reusable `.sage` templates, this skill is the right choice.

Typical use cases:

- solve RSA, ECC, lattice, or hidden-number style challenges
- work with finite-field arithmetic and curve points
- prototype number-theory attacks in a `.sage` file
- use bundled Sage templates for common crypto attack setups

### `ssh-async`

Use this skill when the agent needs a persistent SSH shell rather than a single `ssh host command` call. Like `netcat-async`, it keeps a named session open and lets the agent send commands, inspect output later, and reuse the same authenticated shell context across multiple steps.

It is suited to remote debugging, deployment, log inspection, long-lived administrative sessions, and workflows where the current working directory, shell environment, or prompt state matters. It is deliberately focused on line-oriented shell usage, not full-screen TUI applications.

Typical use cases:

- keep one remote shell open for a whole debugging session
- inspect logs and rerun commands on the same host without reconnecting
- work through a remote challenge environment incrementally
- preserve shell context while iterating on fixes or commands

## Install

Run:

```bash
bash /home/zerotwo/ctf-toolkit-bootstrap/scripts/install.sh
```

Optional:

```bash
bash /home/zerotwo/ctf-toolkit-bootstrap/scripts/install.sh --env myctf
bash /home/zerotwo/ctf-toolkit-bootstrap/scripts/install.sh --dry-run
```

## Verify

Run:

```bash
bash /home/zerotwo/ctf-toolkit-bootstrap/scripts/verify.sh
```

Or verify a different environment:

```bash
bash /home/zerotwo/ctf-toolkit-bootstrap/scripts/verify.sh --env myctf
```

## Skill Injection

The repo carries vendored skills under [skills](/home/zerotwo/ctf-toolkit-bootstrap/skills) and copies them into `~/.codex/skills` during install.

Manual sync:

```bash
bash /home/zerotwo/ctf-toolkit-bootstrap/scripts/sync_skills.sh
```

Manual removal:

```bash
bash /home/zerotwo/ctf-toolkit-bootstrap/scripts/remove_skills.sh
```

## Make Targets

Run:

```bash
make -C /home/zerotwo/ctf-toolkit-bootstrap install ENV=ctf
make -C /home/zerotwo/ctf-toolkit-bootstrap dry-run ENV=ctf
make -C /home/zerotwo/ctf-toolkit-bootstrap verify ENV=ctf
make -C /home/zerotwo/ctf-toolkit-bootstrap uninstall ENV=ctf
make -C /home/zerotwo/ctf-toolkit-bootstrap sync-skills
make -C /home/zerotwo/ctf-toolkit-bootstrap remove-skills
```

## Uninstall

By default, the uninstall script removes the user-local tools and symlinks it created:

```bash
bash /home/zerotwo/ctf-toolkit-bootstrap/scripts/uninstall.sh
```

Optional:

```bash
bash /home/zerotwo/ctf-toolkit-bootstrap/scripts/uninstall.sh --env ctf --remove-env
bash /home/zerotwo/ctf-toolkit-bootstrap/scripts/uninstall.sh --purge-apt
bash /home/zerotwo/ctf-toolkit-bootstrap/scripts/uninstall.sh --dry-run
```

## Notes

- The installer does not remove existing environments or tools.
- The installer checks `conda` on `PATH` first, then common install locations such as `~/miniconda3` and `~/anaconda3`.
- The uninstall script is conservative by default. It does not remove the conda environment or apt packages unless asked.
- The vendored skill sync uses `rsync --delete` per managed skill directory and now also removes the retired `ctf-tools` directory, so repo copies become the source of truth for the OpenCROW toolbox skills plus `minecraft-async`, `netcat-async`, `sagemath`, and `ssh-async` under `~/.codex/skills`.
- `minecraft-async` launches the existing `~/.minecraft` Java client directly for offline usernames and uses X11 automation through `python3-xlib` for fast in-game actions.
- `pwndbg` is installed with the upstream rootless installer.
- `ghidra` is downloaded from the official NSA GitHub release and unpacked under `~/.local/opt/ghidra`.
- `seccomp-tools` is installed with `gem --user-install` and symlinked into `~/.local/bin`.
- The GitHub Actions workflow is a smoke test for script validity and dry-run behavior. It does not download the full toolchain in CI.
