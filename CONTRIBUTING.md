# Contributing to OpenCROW

Use the branch flow and tests documented in [release procedure](docs/contributor/releases.md). Keep canonical Agent Skills provider-neutral, lifecycle helpers standard-library-only, and provider config changes confined to `integrations/` and transactional merge code.

Repository Markdown is authoritative. Public Wiki pages are generated only from `docs/wiki-manifest.json`. Direct edits to generated Wiki pages are unsupported and will be overwritten during the next stable release. Change the repository source and manifest in a pull request instead.

Run `make test`, `make smoke`, and `python3 scripts/validate_docs.py` before submitting.
