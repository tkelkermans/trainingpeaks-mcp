# TrainingPeaks Complete Analysis Contract Design

**Date:** 2026-08-09

## Decision

Replace remote-inaccessible temporary file paths with two additive read-only
interfaces: a paginated TrainingPeaks analysis series and a paginated in-memory
FIT series. Add a separate, non-mutating session classifier that groups likely
copies of one physical ride and selects each canonical field with provenance.

## Problem

`tp_analyze_workout` already receives the full analysis series but writes the
raw response under the server's temporary directory and returns that path. A
remote MCP client cannot read it. `tp_download_workout_file` has the same flaw.
TrainingPeaks can also hold a plan-paired Garmin record, a TP Virtual execution,
and an Apple Health copy for one ride. Summing all rows overstates load.

## Interfaces

### `tp_get_workout_timeseries`

- Inputs: `workout_id`, `offset` (default 0), `limit` (default 500, max 1000),
  optional `channels`, and `include_location` (default false).
- Reuses the Peaksware analysis request in memory.
- Returns `samples`, page metadata, channel inventory, timestamps, availability,
  provenance, and privacy metadata.
- Sample time is explicitly elapsed seconds. Absolute source timestamps are
  retained separately and are never assigned a timezone that the source omits.
- Latitude, longitude and coordinate-like fields are removed unless explicitly
  requested.

### `tp_get_workout_file_timeseries`

- Inputs: `workout_id`, `file_id`, `offset`, `limit`, optional `channels`, and
  `include_location`.
- Downloads bytes through the authenticated TrainingPeaks endpoint, decompresses
  gzip in memory, and decodes FIT with Garmin's official Python SDK.
- Enforces compressed and decompressed size limits and never returns raw bytes,
  signed URLs, or a server path.
- Returns record samples, laps, session metadata, developer-field names and
  units, decoder warnings, page metadata, provenance and privacy metadata.

### `tp_classify_sessions`

- Inputs: two or more workout IDs and optional canonical preference
  (`trainingpeaks_virtual`, `garmin`, or `auto`).
- Fetches detail plus analysis metadata for candidates, identifies provider from
  file metadata and title, and returns pairwise evidence.
- Possible relationship states are `same_session`, `distinct`, and `unresolved`.
- Canonicalization occurs only inside a resolved `same_session` cluster.
  `distinct` candidates remain separate clusters, while `unresolved` candidates
  expose evidence but no combined canonical metrics or excluded load IDs.
- Roles are additive: `plan_anchor`, `execution`, `physiology_auxiliary`, and
  `duplicate_excluded`.
- Canonical metrics are field-level objects with value, unit, source workout and
  method. Canonical TSS is counted once. The tool never pairs, deletes or edits.

Field precedence is deterministic inside a resolved cluster. Planned values and
structure come from `plan_anchor`. Execution laps and duration use the explicit
provider preference when it has a non-null actual value, then TP Virtual, then
the richest non-excluded actual record. Physiological channels use the member
that actually exposes each channel. Actual TSS uses the explicit provider
preference, then a plan-paired device record, then the richest actual record.
Null values fall through. Material conflicting ties are returned as unresolved
for that field instead of being averaged or summed.

## Availability and provenance

Every new tool returns a tagged availability object with `state`, `reason`, and
source. Empty arrays are valid only when the source is available and has zero
records. Every metric/channel states its source and unit. FIT decode warnings
produce `partial`, not silent success.

## Backward compatibility

The new tools are additive. Removing `data_file` from `tp_analyze_workout` is an
intentional response-contract break because a server-local path is unsafe and
unusable for hosted clients. The response retains point count plus a
`time_series_access` object directing callers to `tp_get_workout_timeseries`.
Existing upload/download tools remain available for local workflows.

## Security and privacy

- No server filesystem path, raw file bytes, signed URL, email or coordinate is
  returned by the new remote-safe tools.
- Location requires explicit opt-in.
- Cursor inputs are bounded integer offsets, not opaque user-controlled paths.
- FIT payload size and decompressed size are bounded before decoding.

## August 9 acceptance

- Workout `3875883540` analysis exposes 957 samples without a path.
- Garmin file `-542574935` decodes in memory and exposes power, HR, cadence and
  Tyme developer fields when present.
- IDs `3875883540`, `3892963444`, and `3892964243` form one logical session.
- Canonical load is one value around 19 to 20 TSS, never their sum.
- TP Virtual is execution, Garmin/plan is intent plus physiology, and Apple
  Health is logically excluded without deletion.

## Self-review

The design avoids a cross-provider database inside either vendor connector.
TymeWear remains joined by the coaching caller using timestamps and external
IDs. A stateless Vercel function may refetch a source for later pages, which is
less efficient but avoids unstable server-local cursors. No unsupported
TrainingPeaks mutation is introduced.
