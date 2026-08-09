"""Shared, hosted-safe response helpers for paginated time-series tools."""

import re
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, Field, field_validator

DEFAULT_PAGE_LIMIT = 500
MAX_PAGE_LIMIT = 1000
ELAPSED_TIME_FIELD = "elapsed_seconds"
ELAPSED_TIME_UNIT = "s"

_LOCATION_NAMES = {
    "lat",
    "latitude",
    "lon",
    "long",
    "longitude",
    "lng",
    "positionlat",
    "positionlong",
}
_TIMEZONE_SUFFIX = re.compile(r"(Z|[+-]\d{2}:\d{2})$")


class TimeSeriesPageInput(BaseModel):
    """Validate bounded pagination and optional channel selection."""

    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT)
    channels: list[str] | None = None
    include_location: bool = False

    @field_validator("channels")
    @classmethod
    def validate_channels(cls, channels: list[str] | None) -> list[str] | None:
        if channels is None:
            return None
        normalized: list[str] = []
        for channel in channels:
            name = channel.strip()
            if not name:
                raise ValueError("channel names must not be empty")
            if name not in normalized:
                normalized.append(name)
        return normalized


def is_location_field(name: str) -> bool:
    """Return whether a source field contains latitude/longitude coordinates."""
    normalized = "".join(character for character in name.lower() if character.isalnum())
    return (
        normalized in _LOCATION_NAMES
        or "latitude" in normalized
        or "longitude" in normalized
    )


def _source_timezone(*timestamps: str | None) -> str | None:
    for timestamp in timestamps:
        if timestamp:
            match = _TIMEZONE_SUFFIX.search(timestamp)
            if match:
                return match.group(1)
    return None


def build_timeseries_page(
    *,
    workout_id: int,
    samples: Sequence[Mapping[str, Any]],
    channel_metadata: Sequence[Mapping[str, Any]],
    start_timestamp: str | None,
    stop_timestamp: str | None,
    offset: int,
    limit: int,
    requested_channels: Sequence[str] | None,
    include_location: bool,
    source: str,
    elapsed_source_field: str = "time",
) -> dict[str, Any]:
    """Normalize, redact, filter, and page a source time series in memory."""
    metadata_by_identifier: dict[str, Mapping[str, Any]] = {}
    source_channel_order: list[str] = []
    for metadata in channel_metadata:
        identifier = metadata.get("identifier")
        if not isinstance(identifier, str) or not identifier:
            continue
        metadata_by_identifier[identifier] = metadata
        if identifier not in source_channel_order:
            source_channel_order.append(identifier)

    for sample in samples:
        for field in sample:
            if field in (elapsed_source_field, ELAPSED_TIME_FIELD):
                continue
            if field not in source_channel_order:
                source_channel_order.append(field)

    redacted_fields = [
        field for field in source_channel_order if is_location_field(field)
    ]
    allowed_source_channels = [
        field
        for field in source_channel_order
        if include_location or not is_location_field(field)
    ]
    if requested_channels is None:
        selected_channels = allowed_source_channels
    else:
        selected_channels = [
            field
            for field in requested_channels
            if include_location or not is_location_field(field)
        ]

    total = len(samples)
    raw_page = samples[offset : offset + limit]
    normalized_samples: list[dict[str, Any]] = []
    for sample in raw_page:
        normalized: dict[str, Any] = {
            ELAPSED_TIME_FIELD: sample.get(
                ELAPSED_TIME_FIELD,
                sample.get(elapsed_source_field),
            )
        }
        for field in selected_channels:
            if field in sample:
                normalized[field] = sample[field]
        normalized_samples.append(normalized)

    inventory: list[dict[str, Any]] = []
    units: dict[str, str | None] = {ELAPSED_TIME_FIELD: ELAPSED_TIME_UNIT}
    unavailable_channels: list[str] = []
    for identifier in selected_channels:
        metadata = metadata_by_identifier.get(identifier, {})
        available = identifier in source_channel_order
        unit = metadata.get("unit")
        inventory.append(
            {
                "identifier": identifier,
                "name": metadata.get("name") or identifier,
                "unit": unit,
                "source": source,
                "available": available,
            }
        )
        units[identifier] = unit
        if not available:
            unavailable_channels.append(identifier)

    returned = len(normalized_samples)
    has_more = offset + returned < total
    if unavailable_channels:
        availability_state = "partial"
        availability_reason = (
            "requested_channels_unavailable: " + ", ".join(unavailable_channels)
        )
    elif total == 0:
        availability_state = "available"
        availability_reason = "source_returned_no_samples"
    else:
        availability_state = "available"
        availability_reason = None

    return {
        "workout_id": workout_id,
        "samples": normalized_samples,
        "page": {
            "offset": offset,
            "limit": limit,
            "returned": returned,
            "total": total,
            "has_more": has_more,
            "next_offset": offset + returned if has_more else None,
        },
        "channels": inventory,
        "units": units,
        "timestamps": {
            "start": start_timestamp,
            "stop": stop_timestamp,
            "timezone": _source_timezone(start_timestamp, stop_timestamp),
        },
        "availability": {
            "state": availability_state,
            "reason": availability_reason,
            "source": source,
        },
        "provenance": {
            "source": source,
            "workout_id": workout_id,
        },
        "privacy": {
            "location_included": include_location,
            "redacted_fields": [] if include_location else redacted_fields,
        },
    }
