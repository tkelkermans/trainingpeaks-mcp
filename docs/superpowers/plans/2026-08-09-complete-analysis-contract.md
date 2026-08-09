# TrainingPeaks Complete Analysis Contract Implementation Plan

> Execute with TDD. Each task starts with a failing focused test, then the
> smallest implementation, then focused and full verification.

**Goal:** Make workout samples and duplicate identity usable from the hosted MCP
without server-local files or double-counted load.

**Architecture:** Refactor the existing analysis and raw-file fetches into
in-memory helpers. Build small pure functions for paging, FIT normalization,
privacy filtering, and session classification. Register three additive tools.

**Dependency:** `garmin-fit-sdk==21.212.0`.

## Task 1: Shared response contract and analysis pagination

**Files:** `src/tp_mcp/tools/analyze.py`, new
`src/tp_mcp/tools/analysis_contract.py`, `tests/test_tools/test_analyze.py`, new
`tests/test_tools/test_timeseries.py`.

1. Add failing tests for summary output without `data_file`, page bounds,
   channel filtering, default coordinate removal, explicit location opt-in,
   units, provenance, availability, and a 957-point boundary.
2. Extract `_fetch_workout_analysis()` from `tp_analyze_workout`.
3. Add `tp_get_workout_timeseries()` using offset/limit slicing and explicit
   elapsed-time semantics.
4. Run focused tests and commit.

## Task 2: In-memory FIT decoding

**Files:** `pyproject.toml`, `uv.lock`, `src/tp_mcp/tools/workout_files.py`, new
`src/tp_mcp/tools/fit_timeseries.py`, new
`tests/test_tools/test_fit_timeseries.py`.

1. Add failing pure-normalization tests using decoded-message dictionaries and
   an SDK-encoded small FIT for native fields.
2. Add dependency and a byte-fetch helper that never writes.
3. Implement gzip detection, size guards, SDK decode, developer-field naming,
   timestamp serialization, paging, units, provenance and coordinate filtering.
4. Test malformed, oversized, decoder-warning and gzip inputs.
5. Run focused tests and commit.

## Task 3: Read-only session classification

**Files:** new `src/tp_mcp/tools/session_identity.py`, new
`tests/test_tools/test_session_identity.py`, `src/tp_mcp/tools/workouts.py`.

1. Add a decision-table test for the August 9 Garmin, TP Virtual and Apple
   Health records, plus distinct and unresolved cases. Assert only resolved
   same-session clusters receive combined canonical metrics or excluded IDs.
2. Expose start time and richer file source metadata from workout detail.
3. Implement provider detection, pairwise evidence, roles, deterministic
   planned/execution/physiology/TSS field precedence, null fallback, conflict
   withholding, canonical field provenance and once-only TSS.
4. Assert the function makes only GET/analysis calls and no mutation.
5. Run focused tests and commit.

## Task 4: MCP registration and documentation

**Files:** `src/tp_mcp/tools/__init__.py`, `src/tp_mcp/server.py`,
`tests/test_server_functional.py`, `README.md`.

1. Add failing tool-list and dispatch tests for all three tools.
2. Register schemas and handlers.
3. Replace the hosted temporary-path limitation in README with the new tools,
   limits, privacy defaults and availability states.
4. Run server tests and commit.

## Task 5: Verification and live acceptance

1. Run `uv run ruff check src tests`.
2. Run `uv run mypy src`.
3. Run `PYTHONDONTWRITEBYTECODE=1 uv run pytest -p no:cacheprovider`.
4. Decode the local August 9 TP Virtual FIT without printing coordinates.
5. Deploy the exact feature revision to a Vercel preview and run hosted
   acceptance there.
6. Promote the verified revision to production, then repeat health,
   unauthorized rejection, tool listing, analysis page, FIT page, and August 9
   session-classification smoke tests.
