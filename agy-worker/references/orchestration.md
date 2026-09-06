# AGY Worker Orchestration & Prompt Patterns

This guide outlines best practices for orchestrating Antigravity (`agy`) as an execution worker from higher-level planning agents.

## 1. Core Principles

### Single Responsibility per Turn
Delegate one cohesive task at a time. Rather than asking `agy` to "architect and implement the entire system", ask it to "implement the database schema migration in `schema.sql` and run `db_migrate.py` to verify".

### Explicit Acceptance Criteria
Always tell `agy` how to verify its own work before returning. Examples:
- "After modifying `parser.py`, run `python3 -m unittest tests/test_parser.py` and ensure 0 failures."
- "Verify with `curl -s http://localhost:8080/health` that the endpoint returns `200 OK`."

### Scoped Workspace
Always specify the `workspace` directory explicitly so file paths remain unambiguous.

---

## 2. Common Delegation Prompt Templates

### Pattern A: Feature Implementation with Verification

```text
Task: Implement the export_to_csv feature in src/export.py.
Requirements:
1. Export rows with UTF-8 encoding.
2. Escape commas and quotes properly.
3. Run `pytest tests/test_export.py` to ensure all tests pass.
4. Report the command output and any created files.
```

### Pattern B: Bug Fix and Regression Test

```text
Task: Fix the IndexError occurring when parsing empty payloads in src/parser.py.
Steps:
1. View src/parser.py around line 45.
2. Add a guard check for empty inputs returning None.
3. Add a test case in tests/test_parser.py covering empty inputs.
4. Run `pytest tests/test_parser.py` and confirm all tests pass.
```

### Pattern C: Codebase Search & Fact-Gathering

```text
Task: Search the codebase for all references to deprecated_auth_token.
Steps:
1. Search across the repository for deprecated_auth_token.
2. Summarize each file and line where it is referenced.
3. Do not modify any files.
```

---

## 3. Multi-Turn Feedback Loop

When `agy_execute` returns and tests failed or an edge case was missed:
1. Do not start a brand new conversation.
2. Call `agy_chat` passing the same `conversation_id`.
3. Provide the exact error traceback or failing test name.
4. `agy` will retain context of the files it just edited and will iteratively correct the issue.
