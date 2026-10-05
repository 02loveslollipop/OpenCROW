## Sentinel Run Result

**Outcome:** PR created

**Issue reviewed:** Unhandled Driver Exceptions (Information Disclosure / Internal Server Error) in GridFS

**Severity:** MEDIUM

**Affected component:** services/constellation/constellation/storage.py

**Open PR check:** No overlap found

**Action taken:** Caught `bson.errors.InvalidId` and `gridfs.errors.NoFile` in `download_file`, `download_challenge_file`, and `download_agent_artifact` and translated them to `KeyError` to prevent HTTP 500s.

**Verification:** Ran `make test`.

**Pull request title:** Security: [MEDIUM] Fix unhandled GridFS exception masking on file download service

**Pull request:** PR created

**Journal updated:** Yes
