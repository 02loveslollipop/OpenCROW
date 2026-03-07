---
name: ctf-tools
description: Use the Anaconda `ctf` environment and installed system tooling for CTF tasks outside SageMath. Use when Codex needs Python solver and exploit tooling such as z3, pwntools, angr, claripy, capstone, unicorn, keystone, ropper, r2pipe, scapy, or fpylll, or system tools for pwn and reversing such as pwndbg, ghidra-headless, pwninit, seccomp-tools, gdb, gdbserver, checksec, patchelf, qemu-user, qemu-user-static, radare2, objdump, strace, ltrace, binwalk, gcc, and nasm.
---

# CTF Tools

Use this skill when the task is pwn, reversing, symbolic execution, binary patching, ELF inspection, shellcode work, or non-Sage cryptography in the `ctf` conda environment.

## Quick Start

Run inline Python in `ctf`:

```bash
python /home/zerotwo/.codex/skills/ctf-tools/scripts/run_ctf_python.py --code 'from z3 import *; x = BitVec("x", 32); s = Solver(); s.add(x + 5 == 9); print(s.check()); print(s.model())'
```

Run a Python file in `ctf`:

```bash
python /home/zerotwo/.codex/skills/ctf-tools/scripts/run_ctf_python.py --file /absolute/path/to/solve.py
```

Inventory the installed toolkit:

```bash
python /home/zerotwo/.codex/skills/ctf-tools/scripts/verify_toolkit.py
```

## Workflow

1. Choose `ctf` when the task is solver-heavy or binary-analysis-heavy rather than Sage-specific.
2. For quick experiments, run inline code with `run_ctf_python.py --code`.
3. For real exploits or solvers, create a Python file in the workspace and run it with `--file`.
4. Use native binaries directly when the task is better served by CLI tools such as `checksec`, `r2`, `gdb`, `objdump`, `strace`, `ltrace`, `binwalk`, `patchelf`, or `qemu-aarch64`.
5. Read [references/tooling.md](/home/zerotwo/.codex/skills/ctf-tools/references/tooling.md) when choosing between tools or looking for command patterns.

## Tool Selection

- Use `z3` or `claripy` for constraint solving, bit-vectors, path conditions, and symbolic models.
- Use `pwntools` for exploit scripting, remote I/O, packing/unpacking, cyclic patterns, ROP helpers, and ELF inspection.
- Use `angr` for CFG recovery, symbolic execution, state exploration, and lifting when static reversing is not enough.
- Use `capstone`, `keystone`, and `unicorn` for disassembly, assembly, and emulation in custom scripts.
- Use `ropper`, `ROPgadget`, and `pwntools.ROP` for gadget search and ROP chain construction.
- Use `scapy` for packet crafting, protocol parsing, PCAP inspection, and network challenge automation.
- Use `fpylll` for lattice reduction when the task fits Python better than Sage.
- Use `pwndbg` for GDB sessions that benefit from exploit-centric context, heap helpers, and richer state views.
- Use `ghidra-headless` for scripted binary import, analysis, and decompilation workflows.
- Use `pwninit` to patch challenge binaries against provided libc/ld pairs quickly.
- Use `seccomp-tools` to inspect BPF filters and seccomp sandboxes in hardened pwn binaries.
- Use `radare2`, `objdump`, `strings`, `gdb`, and `gdbserver` for interactive binary reversing and runtime inspection.
- Use `checksec`, `patchelf`, `file`, and `readelf`-style workflows to inspect or patch binaries before exploitation.
- Use `qemu-user` or `qemu-user-static` to run non-native challenge binaries.
- Use `binwalk` for firmware and embedded challenge extraction.

## Installed Stack

### Python modules in `ctf`

- `z3`
- `pwntools`
- `angr`
- `claripy`
- `capstone`
- `unicorn`
- `keystone`
- `ropper`
- `r2pipe`
- `lief`
- `scapy`
- `fpylll`

### System tools

- `gdb`
- `pwndbg`
- `gdbserver`
- `ghidra-headless`
- `pwninit`
- `seccomp-tools`
- `checksec`
- `patchelf`
- `qemu-user`
- `qemu-user-static`
- `radare2`
- `objdump`
- `strace`
- `ltrace`
- `binwalk`
- `gcc`
- `nasm`

## Resources

### scripts/run_ctf_python.py

Use this script to execute inline Python or a Python file in the Anaconda `ctf` environment without relying on the current shell environment.

### scripts/verify_toolkit.py

Use this script to confirm that expected Python modules and system tools are available before starting a larger solve workflow.
