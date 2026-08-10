"""Hosted-safe, in-memory FIT decoding and time-series normalization."""

from __future__ import annotations

import gzip
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from io import BytesIO
from typing import Any

from garmin_fit_sdk import Decoder, Profile, Stream
from pydantic import ValidationError

from tp_mcp.tools.analysis_contract import (
    DEFAULT_PAGE_LIMIT,
    TimeSeriesPageInput,
    build_timeseries_page,
    is_location_field,
    tag_unavailable,
)
from tp_mcp.tools.workout_files import _fetch_workout_file_bytes

SOURCE = "trainingpeaks_fit"
MAX_COMPRESSED_FIT_BYTES = 16 * 1024 * 1024
MAX_DECOMPRESSED_FIT_BYTES = 64 * 1024 * 1024
_GZIP_MAGIC = b"\x1f\x8b"
_DECOMPRESSION_CHUNK_BYTES = 64 * 1024
_MESSAGE_NUMBERS = {"record": 20, "lap": 19, "session": 18}
_OMIT = object()


class _FitPayloadError(ValueError):
    def __init__(self, *, error_code: str, reason: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.reason = reason


def _is_fit_location_field(name: str) -> bool:
    lowered = name.lower()
    return is_location_field(name) or lowered.endswith(("_lat", "_lon", "_long", "_lng"))


def _is_developer_location_field(spec: Mapping[str, Any]) -> bool:
    """Classify a developer field by both declared semantics and emitted name."""
    return _is_fit_location_field(str(spec["name"])) or _is_fit_location_field(str(spec["identifier"]))


def _rfc3339(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    serialized = value.isoformat()
    if value.utcoffset() == timezone.utc.utcoffset(value):
        return serialized.replace("+00:00", "Z")
    return serialized


def _serialize_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return _rfc3339(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bytes | bytearray | memoryview):
        return _OMIT
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            serialized = _serialize_value(item)
            if serialized is not _OMIT:
                normalized[str(key)] = serialized
        return normalized
    if isinstance(value, Sequence) and not isinstance(value, str):
        normalized_items: list[Any] = []
        for item in value:
            serialized = _serialize_value(item)
            if serialized is not _OMIT:
                normalized_items.append(serialized)
        return normalized_items
    return value


def _text_value(value: Any) -> str | None:
    if isinstance(value, str):
        value = value.strip("\x00 ")
        return value or None
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray | str):
        for item in value:
            text = _text_value(item)
            if text:
                return text
    return None


def _integer_value(value: Any, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _profile_units(message_type: str) -> dict[str, str | None]:
    profile = Profile["messages"].get(_MESSAGE_NUMBERS[message_type], {})
    result: dict[str, str | None] = {}
    for field in profile.get("fields", {}).values():
        name = field.get("name")
        if not isinstance(name, str):
            continue
        unit = field.get("units")
        result[name] = unit if isinstance(unit, str) and unit else None
    result["timestamp"] = None
    result["start_time"] = None
    return result


def _developer_specs(
    messages: Mapping[str, Any],
    native_names: set[str],
) -> tuple[list[dict[str, Any]], dict[Any, dict[str, Any]], dict[int, list[dict[str, Any]]]]:
    descriptions = messages.get("field_description_mesgs", [])
    sortable: list[tuple[int, int, int, int | None, Mapping[str, Any]]] = []
    if isinstance(descriptions, Sequence):
        for position, description in enumerate(descriptions):
            if not isinstance(description, Mapping):
                continue
            developer_index = _integer_value(description.get("developer_data_index"))
            definition_number = _integer_value(description.get("field_definition_number"))
            sdk_key = _integer_value(description.get("key")) if description.get("key") is not None else None
            sort_key = sdk_key if sdk_key is not None else position
            sortable.append((developer_index, definition_number, sort_key, sdk_key, description))
    sortable.sort(key=lambda item: item[:3])

    used_names = {*native_names, "elapsed_seconds"}
    specs: list[dict[str, Any]] = []
    by_sdk_key: dict[Any, dict[str, Any]] = {}
    by_definition_number: dict[int, list[dict[str, Any]]] = {}
    for developer_index, definition_number, sort_key, sdk_key, description in sortable:
        declared_name = _text_value(description.get("field_name")) or _text_value(description.get("name"))
        base_name = declared_name or f"developer_{developer_index}_{definition_number}"
        identifier = base_name
        if identifier in used_names:
            identifier = f"{base_name}__developer_{developer_index}_{definition_number}"
        if identifier in used_names:
            identifier = f"{identifier}_{sort_key}"
        used_names.add(identifier)
        spec = {
            "identifier": identifier,
            "name": declared_name or identifier,
            "unit": _text_value(description.get("units")),
            "developer_data_index": developer_index,
            "field_definition_number": definition_number,
            "sdk_key": sdk_key if sdk_key is not None else definition_number,
            "declared": declared_name is not None,
        }
        specs.append(spec)
        if sdk_key is not None:
            by_sdk_key[sdk_key] = spec
        by_definition_number.setdefault(definition_number, []).append(spec)
    return specs, by_sdk_key, by_definition_number


def _developer_spec_for_key(
    key: Any,
    by_sdk_key: Mapping[Any, dict[str, Any]],
    by_definition_number: Mapping[int, list[dict[str, Any]]],
) -> dict[str, Any] | None:
    if key in by_sdk_key:
        return by_sdk_key[key]
    if isinstance(key, tuple) and len(key) == 2:
        developer_index = _integer_value(key[0])
        definition_number = _integer_value(key[1])
        for candidate in by_definition_number.get(definition_number, []):
            if candidate["developer_data_index"] == developer_index:
                return candidate
        return None
    definition_number = _integer_value(key)
    candidates = by_definition_number.get(definition_number, [])
    return candidates[0] if candidates else None


def _unknown_developer_spec(key: Any, used_names: set[str]) -> dict[str, Any]:
    if isinstance(key, tuple) and len(key) == 2:
        developer_index = _integer_value(key[0])
        definition_number = _integer_value(key[1])
        identifier = f"developer_{developer_index}_{definition_number}"
    else:
        developer_index = -1
        definition_number = _integer_value(key)
        identifier = f"developer_field_{key}"
    if identifier in used_names:
        identifier = f"{identifier}__unknown"
    used_names.add(identifier)
    return {
        "identifier": identifier,
        "name": identifier,
        "unit": None,
        "developer_data_index": developer_index,
        "field_definition_number": definition_number,
        "sdk_key": key,
        "declared": False,
    }


def _elapsed_seconds(record: Mapping[str, Any], start: datetime | None) -> float | int | None:
    explicit = record.get("elapsed_seconds", record.get("elapsed_time"))
    if isinstance(explicit, int | float):
        return explicit
    timestamp = record.get("timestamp")
    if isinstance(timestamp, datetime) and start is not None:
        return (timestamp - start).total_seconds()
    return None


def _normalized_message(
    message: Mapping[str, Any],
    *,
    include_location: bool,
    redacted_fields: set[str],
    by_sdk_key: Mapping[Any, dict[str, Any]],
    by_definition_number: Mapping[int, list[dict[str, Any]]],
    developer_specs: list[dict[str, Any]],
    used_names: set[str],
    unknown_specs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for field, value in message.items():
        if field == "developer_fields":
            continue
        field_name = str(field)
        if _is_fit_location_field(field_name) and not include_location:
            redacted_fields.add(field_name)
            continue
        serialized = _serialize_value(value)
        if serialized is not _OMIT:
            normalized[field_name] = serialized

    raw_developer_fields = message.get("developer_fields")
    if isinstance(raw_developer_fields, Mapping):
        for key, value in raw_developer_fields.items():
            spec = _developer_spec_for_key(key, by_sdk_key, by_definition_number)
            if spec is None:
                unknown_key = repr(key)
                spec = unknown_specs.get(unknown_key)
                if spec is None:
                    spec = _unknown_developer_spec(key, used_names)
                    unknown_specs[unknown_key] = spec
                    developer_specs.append(spec)
            if _is_developer_location_field(spec) and not include_location:
                redacted_fields.add(str(spec["identifier"]))
                continue
            serialized = _serialize_value(value)
            if serialized is not _OMIT:
                normalized[spec["identifier"]] = serialized
                spec["available"] = True
    return normalized


def _timestamp_bounds(
    records: Sequence[Mapping[str, Any]],
    sessions: Sequence[Mapping[str, Any]],
) -> tuple[str | None, str | None]:
    record_timestamps = [record.get("timestamp") for record in records if record.get("timestamp") is not None]
    if record_timestamps:
        return str(record_timestamps[0]), str(record_timestamps[-1])
    for session in sessions:
        start = session.get("start_time")
        stop = session.get("timestamp")
        if start is not None or stop is not None:
            return str(start) if start is not None else None, str(stop) if stop is not None else None
    return None, None


def _developer_metadata(
    specs: Sequence[Mapping[str, Any]],
    *,
    workout_id: int,
    file_id: int,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for spec in specs:
        available = bool(spec.get("available"))
        result.append(
            {
                "identifier": spec["identifier"],
                "name": spec["name"],
                "unit": spec["unit"],
                "developer_data_index": spec["developer_data_index"],
                "field_definition_number": spec["field_definition_number"],
                "declared": spec["declared"],
                "source": SOURCE,
                "available": available,
                "availability": {
                    "state": "available" if available else "unavailable",
                    "reason": None if available else "field_not_present",
                    "source": SOURCE,
                },
                "provenance": {
                    "source": SOURCE,
                    "workout_id": workout_id,
                    "file_id": file_id,
                },
            }
        )
    return result


def _normalize_fit_messages(
    messages: Mapping[str, Any],
    *,
    workout_id: int,
    file_id: int,
    offset: int = 0,
    limit: int = DEFAULT_PAGE_LIMIT,
    channels: Sequence[str] | None = None,
    include_location: bool = False,
    warnings: Sequence[str] = (),
) -> dict[str, Any]:
    """Normalize official SDK message dictionaries into the hosted response contract."""
    raw_records = [item for item in messages.get("record_mesgs", []) if isinstance(item, Mapping)]
    raw_laps = [item for item in messages.get("lap_mesgs", []) if isinstance(item, Mapping)]
    raw_sessions = [item for item in messages.get("session_mesgs", []) if isinstance(item, Mapping)]
    native_names = {
        str(field)
        for message in [*raw_records, *raw_laps, *raw_sessions]
        for field in message
        if field != "developer_fields"
    }
    developer_specs, by_sdk_key, by_definition_number = _developer_specs(messages, native_names)
    used_names = {str(name) for name in native_names}
    used_names.update(str(spec["identifier"]) for spec in developer_specs)
    redacted_fields: set[str] = set()
    unknown_specs: dict[str, dict[str, Any]] = {}

    first_timestamp = next(
        (record.get("timestamp") for record in raw_records if isinstance(record.get("timestamp"), datetime)),
        None,
    )
    normalized_records: list[dict[str, Any]] = []
    for record in raw_records:
        normalized = _normalized_message(
            record,
            include_location=include_location,
            redacted_fields=redacted_fields,
            by_sdk_key=by_sdk_key,
            by_definition_number=by_definition_number,
            developer_specs=developer_specs,
            used_names=used_names,
            unknown_specs=unknown_specs,
        )
        normalized["elapsed_seconds"] = _elapsed_seconds(record, first_timestamp)
        normalized_records.append(normalized)

    normalized_laps = [
        _normalized_message(
            lap,
            include_location=include_location,
            redacted_fields=redacted_fields,
            by_sdk_key=by_sdk_key,
            by_definition_number=by_definition_number,
            developer_specs=developer_specs,
            used_names=used_names,
            unknown_specs=unknown_specs,
        )
        for lap in raw_laps
    ]
    normalized_sessions = [
        _normalized_message(
            session,
            include_location=include_location,
            redacted_fields=redacted_fields,
            by_sdk_key=by_sdk_key,
            by_definition_number=by_definition_number,
            developer_specs=developer_specs,
            used_names=used_names,
            unknown_specs=unknown_specs,
        )
        for session in raw_sessions
    ]

    start_timestamp, stop_timestamp = _timestamp_bounds(normalized_records, normalized_sessions)
    visible_developer_specs = [
        spec
        for spec in developer_specs
        if include_location or not _is_developer_location_field(spec)
    ]
    developer_units = {str(spec["identifier"]): spec["unit"] for spec in visible_developer_specs}
    record_units = {**_profile_units("record"), **developer_units}
    channel_names = list(
        dict.fromkeys(
            field
            for record in normalized_records
            for field in record
            if field != "elapsed_seconds"
        )
    )
    channel_metadata = [
        {"identifier": field, "name": field, "unit": record_units.get(field)}
        for field in channel_names
    ]
    private_developer_identifiers = {
        str(spec["identifier"])
        for spec in developer_specs
        if _is_developer_location_field(spec)
    }
    safe_channels = (
        channels
        if include_location or channels is None
        else [
            channel
            for channel in channels
            if not _is_fit_location_field(channel)
            and channel not in private_developer_identifiers
        ]
    )
    page = build_timeseries_page(
        workout_id=workout_id,
        samples=normalized_records,
        channel_metadata=channel_metadata,
        start_timestamp=start_timestamp,
        stop_timestamp=stop_timestamp,
        offset=offset,
        limit=limit,
        requested_channels=safe_channels,
        include_location=include_location,
        source=SOURCE,
        elapsed_source_field="elapsed_seconds",
    )
    page["file_id"] = file_id
    page["laps"] = normalized_laps
    page["sessions"] = normalized_sessions
    lap_units = _profile_units("lap")
    session_units = _profile_units("session")
    page["lap_units"] = {
        field: lap_units.get(field, developer_units.get(field))
        for lap in normalized_laps
        for field in lap
    }
    page["session_units"] = {
        field: session_units.get(field, developer_units.get(field))
        for session in normalized_sessions
        for field in session
    }
    page["decoder_warnings"] = list(warnings)
    page["developer_fields"] = _developer_metadata(
        visible_developer_specs,
        workout_id=workout_id,
        file_id=file_id,
    )
    page["provenance"] = {"source": SOURCE, "workout_id": workout_id, "file_id": file_id}
    for channel in page["channels"]:
        channel["provenance"]["file_id"] = file_id
    page["privacy"]["redacted_fields"] = [] if include_location else sorted(redacted_fields)
    if warnings:
        page["availability"] = {
            "state": "partial",
            "reason": "decoder_warnings",
            "source": SOURCE,
        }
    return page


def _prepare_fit_payload(payload: bytes) -> tuple[bytes, str]:
    if len(payload) > MAX_COMPRESSED_FIT_BYTES:
        raise _FitPayloadError(
            error_code="PAYLOAD_TOO_LARGE",
            reason="compressed_size_limit_exceeded",
            message="Workout file exceeds the compressed FIT size limit.",
        )
    if not payload.startswith(_GZIP_MAGIC):
        if len(payload) > MAX_DECOMPRESSED_FIT_BYTES:
            raise _FitPayloadError(
                error_code="PAYLOAD_TOO_LARGE",
                reason="decompressed_size_limit_exceeded",
                message="Workout file exceeds the decompressed FIT size limit.",
            )
        return payload, "plain"

    chunks: list[bytes] = []
    total = 0
    try:
        with gzip.GzipFile(fileobj=BytesIO(payload), mode="rb") as reader:
            while True:
                remaining = MAX_DECOMPRESSED_FIT_BYTES - total
                chunk = reader.read(min(_DECOMPRESSION_CHUNK_BYTES, remaining + 1))
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_DECOMPRESSED_FIT_BYTES:
                    raise _FitPayloadError(
                        error_code="PAYLOAD_TOO_LARGE",
                        reason="decompressed_size_limit_exceeded",
                        message="Workout file exceeds the decompressed FIT size limit.",
                    )
                chunks.append(chunk)
    except _FitPayloadError:
        raise
    except (EOFError, OSError) as error:
        raise _FitPayloadError(
            error_code="FIT_DECODE_ERROR",
            reason="fit_decode_error",
            message="Workout file is not a valid gzip FIT payload.",
        ) from error
    return b"".join(chunks), "gzip"


def _decode_fit_bytes(payload: bytes) -> tuple[dict[str, Any], list[str]]:
    stream = Stream.from_byte_array(bytearray(payload))
    try:
        messages, errors = Decoder(stream).read()
    finally:
        stream.close()
    normalized_messages: dict[str, Any] = dict(messages) if isinstance(messages, Mapping) else {}
    return normalized_messages, [str(error) for error in errors]


def _is_structurally_fit_payload(payload: bytes) -> bool:
    """Check the FIT header before trusting decoder message/warning output."""
    stream = Stream.from_byte_array(bytearray(payload))
    try:
        return bool(Decoder(stream).is_fit())
    finally:
        stream.close()


def _tagged_failure(*, error_code: str, reason: str, message: str) -> dict[str, Any]:
    return tag_unavailable(
        {"isError": True, "error_code": error_code, "message": message},
        reason=reason,
        source=SOURCE,
    )


def _remote_safe_fetch_failure(fetch_result: Mapping[str, Any], *, file_id: str) -> dict[str, Any]:
    """Replace upstream error detail with stable hosted-safe messages."""
    error_code = str(fetch_result.get("error_code", "API_ERROR"))
    if error_code == "VALIDATION_ERROR":
        reason = "validation_error"
        message = "Invalid workout_id or file_id."
    elif error_code == "NOT_FOUND":
        reason = "file_not_found"
        message = f"Workout file {file_id} not found."
    elif error_code == "PAYLOAD_TOO_LARGE":
        reason = "compressed_size_limit_exceeded"
        message = "Workout file exceeds the compressed FIT size limit."
    elif error_code in {"AUTH_EXPIRED", "AUTH_INVALID"}:
        reason = "workout_file_fetch_error"
        message = "Workout file authentication failed. Re-authenticate."
    else:
        reason = "workout_file_fetch_error"
        message = "Workout file could not be fetched."
    return _tagged_failure(error_code=error_code, reason=reason, message=message)


async def tp_get_workout_file_timeseries(
    workout_id: str,
    file_id: str,
    offset: int = 0,
    limit: int = DEFAULT_PAGE_LIMIT,
    channels: list[str] | None = None,
    include_location: bool = False,
) -> dict[str, Any]:
    """Fetch and decode a TrainingPeaks workout FIT file entirely in memory."""
    try:
        page = TimeSeriesPageInput(
            offset=offset,
            limit=limit,
            channels=channels,
            include_location=include_location,
        )
    except ValidationError:
        return _tagged_failure(
            error_code="VALIDATION_ERROR",
            reason="validation_error",
            message="Invalid pagination or channel parameters.",
        )

    payload, fetch_result = await _fetch_workout_file_bytes(
        workout_id,
        file_id,
        max_bytes=MAX_COMPRESSED_FIT_BYTES,
    )
    if payload is None:
        return _remote_safe_fetch_failure(fetch_result, file_id=file_id)

    try:
        fit_payload, compression = _prepare_fit_payload(payload)
        if not _is_structurally_fit_payload(fit_payload):
            raise _FitPayloadError(
                error_code="FIT_DECODE_ERROR",
                reason="fit_decode_error",
                message="Workout file could not be decoded as FIT.",
            )
        messages, warnings = _decode_fit_bytes(fit_payload)
    except _FitPayloadError as error:
        return _tagged_failure(
            error_code=error.error_code,
            reason=error.reason,
            message=str(error),
        )
    except Exception:
        return _tagged_failure(
            error_code="FIT_DECODE_ERROR",
            reason="fit_decode_error",
            message="Workout file could not be decoded as FIT.",
        )

    if warnings and not any(messages.get(key) for key in ("record_mesgs", "lap_mesgs", "session_mesgs")):
        return _tagged_failure(
            error_code="FIT_DECODE_ERROR",
            reason="fit_decode_error",
            message="Workout file could not be decoded as FIT.",
        )

    result = _normalize_fit_messages(
        messages,
        workout_id=int(workout_id),
        file_id=int(file_id),
        offset=page.offset,
        limit=page.limit,
        channels=page.channels,
        include_location=page.include_location,
        warnings=warnings,
    )
    result["compression"] = compression
    result["compressed_size_bytes"] = len(payload)
    result["decompressed_size_bytes"] = len(fit_payload)
    return result
