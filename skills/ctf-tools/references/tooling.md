# Base CTF Tooling

Use this reference when deciding which installed tool fits a pwn, reversing, or solver task in the `ctf` environment.

## Python in `ctf`

Use `run_ctf_python.py` to avoid depending on the current active shell environment.

Good fits:

- `z3`: SAT/SMT solving, bit-vectors, arithmetic constraints
- `pwntools`: exploit scripts, sockets, ELF parsing, packing, cyclic patterns, ROP helpers
- `angr`: symbolic execution, CFG recovery, state exploration
- `claripy`: symbolic expressions without full angr setup
- `capstone`: disassembly
- `keystone`: assembly
- `unicorn`: CPU emulation
- `ropper`: gadget search
- `r2pipe`: script radare2 from Python
- `lief`: parse and patch binaries
- `scapy`: packet generation, PCAP parsing, and protocol scripting
- `fpylll`: LLL/BKZ lattice reduction in Python

## Native tools

Use these directly from the shell when the task is interactive or binary-centric.

- `checksec <binary>`: inspect NX, PIE, RELRO, canary, and Fortify state
- `pwndbg <binary>`: start GDB with pwndbg’s exploit-oriented interface
- `gdb <binary>`: debug locally
- `gdbserver :1234 <binary>`: expose a target for remote debugging
- `ghidra-headless <project_dir> <project_name> -import <binary>`: import and analyze binaries without the GUI
- `pwninit`: patch a challenge binary against supplied libc and loader files
- `seccomp-tools dump <binary>` or `seccomp-tools disasm <bpf>`: inspect seccomp filters
- `r2 -A <binary>`: analyze a binary in radare2
- `objdump -d <binary>`: fast disassembly
- `strace <binary>`: trace syscalls
- `ltrace <binary>`: trace library calls
- `patchelf --print-interpreter <binary>`: inspect ELF interpreter
- `qemu-aarch64 ./chall`: run an AArch64 userland binary
- `binwalk -e <firmware.bin>`: extract firmware blobs
- `nasm -f elf64 shell.asm`: assemble shellcode or test objects

## Practical selection

- Start with `file`, `checksec`, and `strings` for fast binary triage.
- Move to `objdump` or `r2` for static inspection.
- Use `gdb` or `gdbserver` when behavior depends on runtime state.
- Use `pwntools` for exploit scripts that need process/remote interaction.
- Use `pwndbg` instead of plain `gdb` when the debugging task is exploit-centric.
- Use `z3` or `claripy` when the challenge is constraint-driven.
- Use `angr` only when a smaller static or solver-only approach is not enough; it is heavier but effective.
- Use `ghidra-headless` when the agent needs repeatable decompilation or scripted analysis output.
- Use `pwninit` early for glibc-linked pwn binaries shipped with custom `libc.so.6` or `ld-linux`.
- Use `seccomp-tools` when a binary appears sandboxed or syscall-limited.
- Use `qemu-user` when the challenge binary is not native to the host architecture.
