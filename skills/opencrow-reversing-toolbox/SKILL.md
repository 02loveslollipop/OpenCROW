---
name: opencrow-reversing-toolbox
description: Use the Anaconda `ctf` environment and installed reverse-engineering tooling for binary analysis, symbolic execution, disassembly, emulation, and binary patching. Use when Codex needs `angr`, `claripy`, `capstone`, `unicorn`, `ghidra-headless`, `radare2`, `objdump`, `strace`, `ltrace`, `binwalk`, or related tools.
---

# OpenCROW Reversing Toolbox

Use this skill for understanding binaries rather than exploiting them: disassembly, decompilation support, tracing, symbolic execution, gadget or instruction analysis, and binary rewriting in the `ctf` environment.

## Quick Start

Run inline Python in `ctf`:

```bash
python ~/.codex/skills/opencrow-reversing-toolbox/scripts/run_reversing_python.py --code 'import angr; print(angr.__version__)'
```

Run an analysis helper:

```bash
python ~/.codex/skills/opencrow-reversing-toolbox/scripts/run_reversing_python.py --file /absolute/path/to/analyze.py
```

Verify the mapped stack:

```bash
python ~/.codex/skills/opencrow-reversing-toolbox/scripts/verify_toolkit.py
```

## Workflow

1. Start here when the task is "understand behavior" or "recover logic."
2. Triage with `file`, `strings`, `objdump`, or `r2` before heavier analysis.
3. Use Python tooling such as `angr`, `claripy`, `capstone`, `keystone`, `unicorn`, `ropper`, `r2pipe`, and `lief` for scripted workflows.
4. Use `ghidra-headless`, `strace`, `ltrace`, or `binwalk` when the artifact needs decompilation, tracing, or extraction.
5. Read [references/tooling.md](references/tooling.md) when selecting among the installed reverse-engineering tools.

## Tool Selection

- Use `angr` for CFG recovery, path exploration, symbolic execution, and automated state search.
- Use `claripy` when you need symbolic expressions without a full `angr` workflow.
- Use `capstone`, `keystone`, and `unicorn` for disassembly, assembly, and emulation inside custom scripts.
- Use `ropper` to search gadgets during binary inspection.
- Use `r2pipe` and `radare2` for scriptable or interactive binary analysis.
- Use `lief` for parsing and patching executable formats.
- Use `ghidra-headless` for repeatable import, analysis, and decompilation tasks without the GUI.
- Use `objdump`, `strace`, `ltrace`, and `binwalk` for fast static, runtime, or firmware-oriented inspection.

## Resources

- `scripts/run_reversing_python.py`: execute inline code or a `.py` file inside the `ctf` environment.
- `scripts/verify_toolkit.py`: confirm that the mapped Python and native reversing tools are installed.
- `references/tooling.md`: quick selection notes for reverse-engineering workflows.
