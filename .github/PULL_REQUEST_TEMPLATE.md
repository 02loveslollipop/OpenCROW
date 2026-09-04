## What changes

<!-- One paragraph: problem + fix. Link issue if any. -->

## Why this helps reviewers

<!-- Impact, risk, rollback. Keep it small: one concern per PR. -->

## Verification

- [ ] `PYTHONPATH=installer:packages/lifecycle:packages/mcp/core:packages/mcp/servers:services/constellation:. pytest -q packages/lifecycle/tests packages/mcp/tests installer/tests tests`
- [ ] `make smoke`
- [ ] `python3 scripts/validate_docs.py`
- [ ] `bash installer/install.sh --agents codex --toolboxes utility --no-miniconda --yes --dry-run`

## Checklist

- [ ] One concern per PR, no drive-by refactors
- [ ] Provider-neutral skills untouched unless intended (`skills/`)
- [ ] No secrets, tokens, or local paths committed
- [ ] Docs updated if behavior changed
