---
name: opencrow-crypto-toolbox
description: Use the Anaconda `ctf` environment for CTF cryptography work that fits normal Python rather than SageMath. Use when Codex needs constraint solving, lattice reduction, or quick crypto helper scripts with `z3`, `fpylll`, or related Python tooling.
---

# OpenCROW Crypto Toolbox

Use this skill for Python-first crypto tasks in the `ctf` environment: SMT constraints, bit-vector modeling, lattice experiments with `fpylll`, and glue code around challenge artifacts. If the task depends on Sage objects, finite fields, or heavy algebra, use `sagemath` instead.

## Quick Start

Run inline Python in `ctf`:

```bash
python ~/.codex/skills/opencrow-crypto-toolbox/scripts/run_crypto_python.py --code 'from z3 import *; x = BitVec("x", 32); s = Solver(); s.add(x ^ 0x1337 == 0x1234); print(s.check()); print(s.model())'
```

Run a solver file:

```bash
python ~/.codex/skills/opencrow-crypto-toolbox/scripts/run_crypto_python.py --file /absolute/path/to/solve.py
```

Verify the mapped stack:

```bash
python ~/.codex/skills/opencrow-crypto-toolbox/scripts/verify_toolkit.py
```

## Workflow

1. Use this toolbox when the job is mostly Python, constraints, lattices, or byte-level crypto helpers.
2. Use `run_crypto_python.py --code` for short experiments and `--file` for real solve scripts.
3. Reach for `z3` when the challenge is equation- or bit-vector-driven.
4. Reach for `fpylll` when the attack is lattice-driven and does not require Sage.
5. Read [references/tooling.md](references/tooling.md) if you need a quick selection guide.

## Tool Selection

- Use `z3` for SAT/SMT solving, bit-vectors, modular constraints, and key-recovery models that can be expressed symbolically.
- Use `fpylll` for LLL/BKZ lattice reduction, CVP experiments, and short-vector workflows in plain Python.
- Use standard Python libraries in the same script for parsing challenge formats, padding oracles, byte wrangling, and protocol glue.
- Switch to `sagemath` when the task needs finite fields, elliptic curves, polynomial rings, or Sage-native attack code.

## Resources

- `scripts/run_crypto_python.py`: execute inline code or a `.py` file inside the `ctf` environment.
- `scripts/verify_toolkit.py`: confirm that the crypto-specific Python modules are available.
- `references/tooling.md`: quick guidance on when to stay in Python crypto tooling versus switching to Sage.
