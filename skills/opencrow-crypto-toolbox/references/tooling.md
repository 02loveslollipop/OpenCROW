# OpenCROW Crypto Toolbox

Use this reference when choosing between the Python-first crypto tools mapped into the `ctf` environment.

## Python modules

- `z3`: SAT/SMT solving, bit-vectors, arithmetic constraints, state recovery, and symbolic key search.
- `fpylll`: LLL and BKZ lattice reduction for Hidden Number, approximate common divisor, knapsack, and Coppersmith-adjacent workflows when Sage is unnecessary.

## Practical selection

- Start with `z3` when the unknowns are discrete variables and the relationships are exact.
- Start with `fpylll` when the attack is "build a basis, reduce it, and inspect short vectors."
- Use plain Python around both libraries for parsing packets, ciphertext blobs, or challenge-specific encodings.
- Switch to `sagemath` when the task needs finite fields, elliptic curves, polynomial rings, resultants, or Sage-native lattice helpers.
