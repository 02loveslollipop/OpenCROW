# Security / Sentinel PR review — 2026-10-25

Reviewed 46 open PRs whose author is exactly `02loveslollipop` and whose title contains Security or Sentinel. No other PRs were opened, reviewed, merged or modified. PR bodies, complete diffs, changed files, head SHAs, mergeability and check results were downloaded for this scope. Snapshot: `inventory.json` and numbered `.json` / `.diff` files in `/tmp/opencrow-security-review-20261025`.

Integration base: `4769d0cf549f434dc2fed978df5be0ea7fc8f283` (`origin/main`, fetched live). Local branch: `review/security-staged-20261025`. Worktree: `/tmp/opencrow-security-staged-20261025`. Original checkout and its pre-existing uncommitted changes were preserved. No GitHub merges, branch pushes, PR comments or duplicate closures were performed.

## Grouping and selection

| Issue group | PRs | Selection |
| --- | --- | --- |
| Token comparison robustness (21) | #163, #166, #168, #177, #181, #185, #187, #188, #189, #190, #194, #195, #200, #202, #203, #205, #209, #210, #211, #212, #213 | #212 foundation + #213 Unicode complement; stage 5 completes worker coverage |
| GridFS error translation (18) | #164, #165, #167, #169, #174, #175, #176, #178, #179, #182, #183, #184, #186, #192, #193, #199, #201, #206 | #167 |
| WebSocket origin policy (6) | #170, #171, #172, #173, #191, #204 | #170 |
| Mislabeled / no security fix (1) | #180 | None; reject #180 |

Mixed PRs #177 and #188 also overlap the GridFS group; each is counted once under token robustness. One primary winner per issue is chosen, with #213 retained as a necessary complementary sub-fix rather than discarded as a duplicate.

## What the source actually establishes

- Authentication: type guards alone do not protect `compare_digest` against non-ASCII strings. A new regression reproduced `Runner.report(..., "雪", ...)` raising TypeError after all four selected PRs were integrated. Stage 5 applies #213 UTF-8 comparison to all eight worker comparisons, preserving #212 type guards. This is a demonstrated availability/input-handling defect; an authentication bypass was not demonstrated.
- GridFS: current main already catches all exceptions in the three HTTP download handlers, logs them server-side, and returns generic 404 reasons. These PRs improve the storage exception contract; their descriptions do not establish a current client-visible stack-trace leak. #167 covers opening, reading and metadata access, without redundant API catches. Real database failures still propagate from storage; existing HTTP catch-all behavior remains.
- WebSockets: a Bearer-header presence currently bypasses the topic socket origin policy, while `open()` still validates the token. A browser CSWSH exploit was not demonstrated. #170 consistently enforces the configured origins, matching the runtime socket. No-Origin clients remain accepted at the origin-policy step and still require token authentication. Clients supplying an unallowlisted Origin will now fail even with a valid Bearer token; configure `OPENCROW_CONSTELLATION_ALLOWED_WS_ORIGINS` for their trusted Origin.
- #204 is not documentation-only: it adds a Bearer-header origin bypass to the runtime socket, broadening behavior. #180 does not contain its claimed authentication fix.

## Staged local merges

| Stage | Selected PR / change | Pinned PR head | Resulting local commit |
| --- | --- | --- | --- |
| 1 | #212 | `be36c179c1a431391e8cdc8e44efa9163d81d79d` | `32b0cf5aea5ee6a62f64c16be506c5ea3448ebd4` |
| 2 | #213 | `2cc022529cbeab23aa87ac3f591aae7f38071fc1` | `ee1e10d37ed9ef75d1a58615ad8492affe33ac3a` |
| 3 | #167 | `63813ae6b9a7bf4eabd38edc4acc1e8f7157e5e5` | `660e55207077a26055d7289e89741e166f3cee48` |
| 4 | #170 | `294d0287153db35bbbb9d8a58ee6bd5627a4c1b9` | `d2c452c2c75846f087cc6ce39827590cb9943bc1` |
| 5 | Complete worker Unicode safety + 45 regressions | `Local completion patch` | `b41e5199dc35144b853ba1f0c13e14c0754fd7cf` |

Stage 2 resolves add/add journal conflicts by retaining both entries, takes #213 typed byte comparisons in backend/system-token validation, and retains #212 single resume-secret digest calculation with byte comparison. Stages 3 and 4 merge without source conflicts. Stage 5 is required before promoting the aggregate branch. No unselected PR heads were merged.

The aggregate branch preserves each selected PR head as an ancestor through actual local merge commits. Promote the final, fully tested branch as one update to avoid exposing incomplete intermediate token hardening. Do not merge duplicate alternatives afterward. Recheck current main and selected PR heads before any remote action.

## Per-PR findings

| PR | Actual change and disposition |
| --- | --- |
| [163](https://github.com/02loveslollipop/OpenCROW/pull/163) | Guards None in worker/backend/storage comparisons; other types and Unicode still raise; redundant digest calculation. Superseded by #212 + #213. |
| [164](https://github.com/02loveslollipop/OpenCROW/pull/164) | Maps InvalidId/NoFile to KeyError for all three downloads, only around stream opening; adds unrelated .gitignore/report.md. Prefer #167. |
| [165](https://github.com/02loveslollipop/OpenCROW/pull/165) | Maps invalid IDs and missing files at stream opening for all three download methods; misses read-time errors. Prefer #167. |
| [166](https://github.com/02loveslollipop/OpenCROW/pull/166) | Guards None in eight worker comparisons only; other types, Unicode and Constellation paths remain. Prefer #212 + #213. |
| [167](https://github.com/02loveslollipop/OpenCROW/pull/167) | SELECTED: translates InvalidId/NoFile across open/read/metadata for all three downloads, with exception chaining and only storage.py changed. |
| [168](https://github.com/02loveslollipop/OpenCROW/pull/168) | Guards None in workers/backend/storage; does not reject other types or Unicode. Prefer #212 + #213. |
| [169](https://github.com/02loveslollipop/OpenCROW/pull/169) | Maps download open errors to KeyError; repeats local imports and adds journal; leaves read outside try. Prefer #167. |
| [170](https://github.com/02loveslollipop/OpenCROW/pull/170) | SELECTED: removes the three-line Bearer-header origin bypass from ConstellationWebSocket; matches runtime socket policy without unrelated edits. |
| [171](https://github.com/02loveslollipop/OpenCROW/pull/171) | Same three-line functional change as #170. Duplicate; earliest equivalent #170 selected. |
| [172](https://github.com/02loveslollipop/OpenCROW/pull/172) | Same three-line functional change as #170. Duplicate; earliest equivalent #170 selected. |
| [173](https://github.com/02loveslollipop/OpenCROW/pull/173) | Same origin-policy change as #170 plus a comment claiming CSWSH prevention; #170 avoids an unsupported exploit claim. |
| [174](https://github.com/02loveslollipop/OpenCROW/pull/174) | Maps download open errors to KeyError for all three methods; misses read-time errors. Prefer #167. |
| [175](https://github.com/02loveslollipop/OpenCROW/pull/175) | Covers full download operations but adds redundant KeyError handlers before existing catch-all sanitized 404 handlers. #167 has the same storage benefit with smaller scope. |
| [176](https://github.com/02loveslollipop/OpenCROW/pull/176) | Open-only GridFS guards plus unrelated netcat timing-test edits. Prefer #167. |
| [177](https://github.com/02loveslollipop/OpenCROW/pull/177) | Mixed token None guards and GridFS open-error conversion; omits download_agent_artifact conversion. Superseded by selected token and storage fixes. |
| [178](https://github.com/02loveslollipop/OpenCROW/pull/178) | Full-operation GridFS guards equivalent to #167 plus redundant backend KeyError handlers. Prefer #167. |
| [179](https://github.com/02loveslollipop/OpenCROW/pull/179) | Open-only GridFS guards plus unrelated installer-test timeout edits. Prefer #167. |
| [180](https://github.com/02loveslollipop/OpenCROW/pull/180) | REJECT: diff contains fix_selector.py, a shell comment and installer SIGINT-test changes; no compare_digest or authentication fix despite title/body. |
| [181](https://github.com/02loveslollipop/OpenCROW/pull/181) | None guards across workers/backend/storage; leaves other malformed types and Unicode untreated. Prefer #212 + #213. |
| [182](https://github.com/02loveslollipop/OpenCROW/pull/182) | Open-only GridFS exception translation, all three methods. Prefer #167 for read coverage. |
| [183](https://github.com/02loveslollipop/OpenCROW/pull/183) | Open-only GridFS exception translation, all three methods. Prefer #167 for read coverage. |
| [184](https://github.com/02loveslollipop/OpenCROW/pull/184) | Open-only GridFS exception translation without explicit exception chaining. Prefer #167. |
| [185](https://github.com/02loveslollipop/OpenCROW/pull/185) | None guards across workers/backend/storage/UI, including redundant UI checks; non-string and Unicode values remain unsafe. Prefer #212 + #213. |
| [186](https://github.com/02loveslollipop/OpenCROW/pull/186) | Open-only GridFS translation using imported exception classes. Prefer #167 for read coverage. |
| [187](https://github.com/02loveslollipop/OpenCROW/pull/187) | None guards only in eight worker comparisons; incomplete type/path coverage. Prefer #212 + #213. |
| [188](https://github.com/02loveslollipop/OpenCROW/pull/188) | Mixed backend/storage None guards, open-only GridFS handling and unrelated narrowing of ObjectId exception catches; no worker fix. Prefer focused selected PRs. |
| [189](https://github.com/02loveslollipop/OpenCROW/pull/189) | None guards in workers/backend/system token checks; omits resume/UI and other types/Unicode. Prefer #212 + #213. |
| [190](https://github.com/02loveslollipop/OpenCROW/pull/190) | None guards in workers/backend/storage/UI; includes always-false str(session_token) is None check; no Unicode fix. Prefer #212 + #213. |
| [191](https://github.com/02loveslollipop/OpenCROW/pull/191) | Same origin-policy change as #170 plus unrelated netcat timing-test changes. Prefer #170. |
| [192](https://github.com/02loveslollipop/OpenCROW/pull/192) | Open-only GridFS translation plus submission.md artifact. Prefer #167. |
| [193](https://github.com/02loveslollipop/OpenCROW/pull/193) | Open-only GridFS exception translation, all three methods. Prefer #167 for read coverage. |
| [194](https://github.com/02loveslollipop/OpenCROW/pull/194) | None guards only in eight worker comparisons. Prefer #212 + #213 for full type/path coverage. |
| [195](https://github.com/02loveslollipop/OpenCROW/pull/195) | None guards across workers/backend/storage/UI plus journal; other types and Unicode remain unsafe. Prefer #212 + #213. |
| [199](https://github.com/02loveslollipop/OpenCROW/pull/199) | Covers GridFS open and read, all three methods, plus journal. #167 also covers metadata access with no journal addition. |
| [200](https://github.com/02loveslollipop/OpenCROW/pull/200) | None guards only in backend/storage; workers and Unicode remain unprotected. Prefer #212 + #213. |
| [201](https://github.com/02loveslollipop/OpenCROW/pull/201) | Open-only GridFS guards plus journal. Prefer #167. |
| [202](https://github.com/02loveslollipop/OpenCROW/pull/202) | None guards across workers/backend/storage/UI; redundant checks and no non-string/Unicode protection. Prefer #212 + #213. |
| [203](https://github.com/02loveslollipop/OpenCROW/pull/203) | None guards in workers/backend/storage. Critical severity/auth bypass claims not established by diff; prefer #212 + #213. |
| [204](https://github.com/02loveslollipop/OpenCROW/pull/204) | REJECT: preserves topic-socket bypass and introduces a new bypass into RuntimeControlWebSocket, despite documentation-only title; conflicts with selected origin policy. |
| [205](https://github.com/02loveslollipop/OpenCROW/pull/205) | None guards only in storage; preserves other-type/Unicode crashes and leaves workers/backend/UI unchanged. Prefer #212 + #213. |
| [206](https://github.com/02loveslollipop/OpenCROW/pull/206) | Open-only GridFS exception translation, all three methods. Prefer #167. |
| [209](https://github.com/02loveslollipop/OpenCROW/pull/209) | Worker/backend None guards, redundant resume-digest None guard and UI string conversion; does not prevent Unicode crashes. Prefer #212 + #213. |
| [210](https://github.com/02loveslollipop/OpenCROW/pull/210) | Strong string-type guards in workers/backend/storage, but computes resume digest twice and leaves Unicode crashes. #212 improves hashing; #213 complements Unicode coverage. |
| [211](https://github.com/02loveslollipop/OpenCROW/pull/211) | String-type guards like #210 plus unrelated netcat-test edits; repeated digest computation. Prefer #212. |
| [212](https://github.com/02loveslollipop/OpenCROW/pull/212) | SELECTED type-safety foundation: checks string types in all eight worker comparisons and backend/storage; hashes resume secret once; no unrelated test edits. Still needs Unicode complement. |
| [213](https://github.com/02loveslollipop/OpenCROW/pull/213) | SELECTED complementary Unicode fix: compares UTF-8 bytes in backend/storage/UI and validates system-token types. Does not cover workers; stage 5 extends it to all eight worker comparisons. |

## Validation

All 46 scoped PRs reported mergeable/clean and five successful GitHub checks at inspection. Those checks were on individual PRs and do not certify the aggregate integration.

New behavioral regressions cover malformed system tokens, UI auth, Unicode CSRF rejection, all three GridFS methods (invalid ID, missing stream, read-time disappearance, success, database outage), generic HTTP 404 mapping, both WebSocket handlers with valid Bearer headers, and rejected worker-report tokens without event writes. Before stage 5: 44 passed, 1 failed (worker Unicode TypeError). After stage 5: 45 passed.

Full suite result: **310 passed, 1 skipped in 53.11 seconds**. `make smoke` also passed (shell syntax, Python compilation, documentation validation, lifecycle dry run, installer dry run). `git diff --check` passed. Log: `/tmp/opencrow-security-review-20261025/full-test.log`.

Test environment is an isolated Python 3.12 venv with `services/constellation/requirements.txt` and pytest. The project Makefile PYTHONPATH is exported for subprocess imports. An initial run without that exported path had one worker subprocess import failure (135 passed); this was an invocation issue, not a passing source validation. An earlier attempted run during the stage-2 conflict was invalid and is not counted as validation.

Full-suite command:

```sh
PYTHONPATH=installer:packages/lifecycle:packages/mcp/core:packages/mcp/servers:services/constellation:. \
  /tmp/opencrow-security-review-20261025/venv/bin/python -m pytest -q \
  packages/lifecycle/tests packages/mcp/tests installer/tests services/constellation/tests tests
```

## Prepared artifacts

- `/tmp/opencrow-security-review-20261025/security-staged.bundle`: transferable aggregate Git history, requiring the recorded main base.
- `/tmp/opencrow-security-review-20261025/merge-plan.json`: machine-readable issue groups, stage commits, pinned heads and validation results.
- Branches `review/security-stage-1-20261025` through `review/security-stage-5-20261025`: exact local stage checkpoints.
- `review/security-staged-20261025`: final aggregate branch, including this review.
- Selected heads were revalidated after tests: all four remain open, authored by the permitted user, with unchanged eligible titles and SHAs.

No deployment or live MongoDB integration test was performed; the storage tests use controlled driver/stream mocks. Duplicate PRs remain open, and no other authors or non-Security/Sentinel PRs were reviewed.
