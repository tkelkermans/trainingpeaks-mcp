"""Tests for hosted-safe, in-memory FIT time-series access."""

from __future__ import annotations

import gzip
from datetime import datetime, timedelta, timezone
from importlib import import_module
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from tp_mcp.client.http import ErrorCode, RawResponse

WORKOUT_ID = 3875883540
FILE_ID = -542574935
SOURCE = "trainingpeaks_fit"


def _fit_module():
    try:
        return import_module("tp_mcp.tools.fit_timeseries")
    except ModuleNotFoundError:
        pytest.fail("tp_mcp.tools.fit_timeseries must be implemented")


def _decoded_messages(count: int = 3) -> dict[str, list[dict[str, Any]]]:
    start = datetime(2026, 8, 9, 10, 0, tzinfo=timezone.utc)
    return {
        "record_mesgs": [
            {
                "timestamp": start + timedelta(seconds=index),
                "power": 250 + index,
                "heart_rate": 140 + index,
                "position_lat": 550_000_000 + index,
                "position_long": 90_000_000 + index,
                "developer_fields": {
                    3: 31.5 + index,
                    4: 32.5 + index,
                    5: 300 + index,
                    6: 46.0 + index,
                    99: 7 + index,
                },
            }
            for index in range(count)
        ],
        "lap_mesgs": [
            {
                "timestamp": start + timedelta(seconds=count),
                "start_position_lat": 550_000_000,
                "end_position_long": 90_000_000,
                "total_elapsed_time": float(count),
                "avg_power": 251,
            }
        ],
        "session_mesgs": [
            {
                "start_time": start,
                "timestamp": start + timedelta(seconds=count),
                "start_position_lat": 550_000_000,
                "nec_lat": 560_000_000,
                "total_elapsed_time": float(count),
                "avg_power": 251,
            }
        ],
        "field_description_mesgs": [
            {
                "developer_data_index": 1,
                "field_definition_number": 4,
                "field_name": "respiration_rate",
                "units": "brpm",
            },
            {
                "developer_data_index": 0,
                "field_definition_number": 5,
                "field_name": "power",
                "units": "W",
            },
            {
                "developer_data_index": 0,
                "field_definition_number": 3,
                "field_name": "respiration_rate",
                "units": "brpm",
            },
            {
                "developer_data_index": 0,
                "field_definition_number": 6,
                "field_name": "custom_lat",
                "units": "degrees",
            },
        ],
    }


def _normalize(
    messages: dict[str, list[dict[str, Any]]],
    **kwargs: Any,
) -> dict[str, Any]:
    module = _fit_module()
    normalize = getattr(module, "_normalize_fit_messages", None)
    assert normalize is not None, "_normalize_fit_messages must be implemented"
    return normalize(
        messages,
        workout_id=WORKOUT_ID,
        file_id=FILE_ID,
        **kwargs,
    )


def _encoded_native_fit() -> bytes:
    sdk = pytest.importorskip("garmin_fit_sdk")
    encoder = sdk.Encoder()
    start = datetime(2026, 8, 9, 10, 0, tzinfo=timezone.utc)
    encoder.write_mesg(
        {
            "mesg_num": 20,
            "timestamp": start,
            "power": 250,
            "heart_rate": 140,
            "cadence": 90,
            "position_lat": 550_000_000,
            "position_long": 90_000_000,
        }
    )
    encoder.write_mesg(
        {
            "mesg_num": 20,
            "timestamp": start + timedelta(seconds=1),
            "power": 260,
            "heart_rate": 142,
            "cadence": 92,
            "position_lat": 550_000_001,
            "position_long": 90_000_001,
        }
    )
    encoder.write_mesg(
        {
            "mesg_num": 19,
            "timestamp": start + timedelta(seconds=2),
            "total_elapsed_time": 2.0,
            "avg_power": 255,
        }
    )
    encoder.write_mesg(
        {
            "mesg_num": 18,
            "start_time": start,
            "timestamp": start + timedelta(seconds=2),
            "total_elapsed_time": 2.0,
            "avg_power": 255,
        }
    )
    return encoder.close()


def _encoded_empty_fit() -> bytes:
    sdk = pytest.importorskip("garmin_fit_sdk")
    return sdk.Encoder().close()


async def _call_tool(payload: bytes, **kwargs: Any) -> dict[str, Any]:
    module = _fit_module()
    tool = getattr(module, "tp_get_workout_file_timeseries", None)
    assert tool is not None, "tp_get_workout_file_timeseries must be implemented"
    metadata = {
        "workout_id": str(WORKOUT_ID),
        "file_id": str(FILE_ID),
        "content_type": "application/octet-stream",
        "size_bytes": len(payload),
    }
    with patch(
        "tp_mcp.tools.fit_timeseries._fetch_workout_file_bytes",
        new=AsyncMock(return_value=(payload, metadata)),
    ):
        return await tool(str(WORKOUT_ID), str(FILE_ID), **kwargs)


def test_normalizes_records_laps_sessions_and_rfc3339_timestamps():
    result = _normalize(_decoded_messages())

    assert result["samples"][0] == {
        "elapsed_seconds": 0.0,
        "timestamp": "2026-08-09T10:00:00Z",
        "power": 250,
        "heart_rate": 140,
        "respiration_rate": 31.5,
        "respiration_rate__developer_1_4": 32.5,
        "power__developer_0_5": 300,
        "developer_field_99": 7,
    }
    assert result["laps"] == [
        {
            "timestamp": "2026-08-09T10:00:03Z",
            "total_elapsed_time": 3.0,
            "avg_power": 251,
        }
    ]
    assert result["sessions"] == [
        {
            "start_time": "2026-08-09T10:00:00Z",
            "timestamp": "2026-08-09T10:00:03Z",
            "total_elapsed_time": 3.0,
            "avg_power": 251,
        }
    ]
    assert result["timestamps"] == {
        "start": "2026-08-09T10:00:00Z",
        "stop": "2026-08-09T10:00:02Z",
        "timezone": "Z",
    }


def test_maps_developer_definition_names_units_collisions_and_unknown_fields():
    result = _normalize(_decoded_messages(), channels=["respiration_rate", "developer_field_99"])

    assert result["samples"][0] == {
        "elapsed_seconds": 0.0,
        "respiration_rate": 31.5,
        "developer_field_99": 7,
    }
    assert result["units"] == {
        "elapsed_seconds": "s",
        "respiration_rate": "brpm",
        "developer_field_99": None,
    }
    developer_fields = {entry["identifier"]: entry for entry in result["developer_fields"]}
    assert developer_fields["respiration_rate"]["field_definition_number"] == 3
    assert developer_fields["respiration_rate"]["developer_data_index"] == 0
    assert developer_fields["respiration_rate__developer_1_4"]["unit"] == "brpm"
    assert developer_fields["power__developer_0_5"]["unit"] == "W"
    assert developer_fields["developer_field_99"]["declared"] is False
    assert "developer_field_99__unknown" not in result["samples"][1]


def test_paginates_records_with_defaults_and_bounded_channel_filtering():
    messages = _decoded_messages(count=1001)
    first = _normalize(messages, channels=["power"])
    result = _normalize(messages, offset=500, limit=500, channels=["power"])

    assert first["page"]["limit"] == 500
    assert first["page"]["returned"] == 500
    assert result["page"] == {
        "offset": 500,
        "limit": 500,
        "returned": 500,
        "total": 1001,
        "has_more": True,
        "next_offset": 1000,
    }
    assert result["samples"][0] == {"elapsed_seconds": 500.0, "power": 750}
    assert result["samples"][-1] == {"elapsed_seconds": 999.0, "power": 1249}
    assert result["channels"][0]["identifier"] == "power"
    assert result["channels"][0]["unit"] == "watts"
    assert result["channels"][0]["provenance"] == {
        "source": SOURCE,
        "workout_id": WORKOUT_ID,
        "file_id": FILE_ID,
    }


def test_redacts_coordinate_like_fields_everywhere_unless_explicitly_requested():
    private = _normalize(_decoded_messages())
    private_requested = _normalize(_decoded_messages(), channels=["power", "custom_lat"])
    public = _normalize(_decoded_messages(), include_location=True)

    assert set(private["privacy"]["redacted_fields"]) == {
        "position_lat",
        "position_long",
        "start_position_lat",
        "end_position_long",
        "nec_lat",
        "custom_lat",
    }
    assert "position_lat" not in private["samples"][0]
    assert "start_position_lat" not in private["laps"][0]
    assert "nec_lat" not in private["sessions"][0]
    assert "custom_lat" not in private["samples"][0]
    assert "custom_lat" not in {field["identifier"] for field in private["developer_fields"]}
    assert [field["identifier"] for field in private_requested["channels"]] == ["power"]
    assert "custom_lat" not in private_requested["units"]
    assert public["samples"][0]["position_lat"] == 550_000_000
    assert public["laps"][0]["end_position_long"] == 90_000_000
    assert public["sessions"][0]["nec_lat"] == 560_000_000
    assert public["samples"][0]["custom_lat"] == 46.0


def test_redacts_developer_coordinate_using_declared_semantics_after_name_collision():
    timestamp = datetime(2026, 8, 9, 10, 0, tzinfo=timezone.utc)
    messages = {
        "record_mesgs": [
            {
                "timestamp": timestamp,
                "position_lat": 550_000_000,
                "developer_fields": {6: 46.0},
            }
        ],
        "field_description_mesgs": [
            {
                "developer_data_index": 0,
                "field_definition_number": 6,
                "field_name": "position_lat",
                "units": "degrees",
            }
        ],
    }

    private = _normalize(messages)
    private_requested = _normalize(messages, channels=["position_lat__developer_0_6"])
    public = _normalize(messages, include_location=True)

    renamed = "position_lat__developer_0_6"
    assert renamed not in private["samples"][0]
    assert renamed not in private["units"]
    assert renamed not in {channel["identifier"] for channel in private["channels"]}
    assert renamed not in {field["identifier"] for field in private["developer_fields"]}
    assert renamed not in {channel["identifier"] for channel in private_requested["channels"]}
    assert renamed not in private_requested["units"]
    assert renamed in private["privacy"]["redacted_fields"]
    assert public["samples"][0][renamed] == 46.0
    assert public["units"][renamed] == "degrees"


def test_treats_naive_fit_datetimes_as_utc_rfc3339():
    messages = _decoded_messages(count=1)
    messages["record_mesgs"][0]["timestamp"] = datetime(2026, 8, 9, 10, 0)

    result = _normalize(messages)

    assert result["samples"][0]["timestamp"] == "2026-08-09T10:00:00Z"
    assert result["timestamps"]["start"] == "2026-08-09T10:00:00Z"


def test_decoder_warnings_make_available_data_partial():
    result = _normalize(_decoded_messages(), warnings=["file CRC mismatch"])

    assert result["decoder_warnings"] == ["file CRC mismatch"]
    assert result["availability"] == {
        "state": "partial",
        "reason": "decoder_warnings",
        "source": SOURCE,
    }


@pytest.mark.asyncio
async def test_decodes_an_sdk_encoded_native_fit_entirely_in_memory():
    result = await _call_tool(_encoded_native_fit(), channels=["power", "heart_rate", "cadence"])

    assert result["samples"] == [
        {"elapsed_seconds": 0.0, "power": 250, "heart_rate": 140, "cadence": 90},
        {"elapsed_seconds": 1.0, "power": 260, "heart_rate": 142, "cadence": 92},
    ]
    assert result["units"] == {
        "elapsed_seconds": "s",
        "power": "watts",
        "heart_rate": "bpm",
        "cadence": "rpm",
    }
    assert result["laps"][0]["avg_power"] == 255
    assert result["sessions"][0]["avg_power"] == 255
    assert result["provenance"] == {
        "source": SOURCE,
        "workout_id": WORKOUT_ID,
        "file_id": FILE_ID,
    }


@pytest.mark.asyncio
async def test_decodes_gzip_fit_with_bounded_streaming_decompression():
    result = await _call_tool(gzip.compress(_encoded_native_fit()), channels=["power"])

    assert result["samples"] == [
        {"elapsed_seconds": 0.0, "power": 250},
        {"elapsed_seconds": 1.0, "power": 260},
    ]
    assert result["compression"] == "gzip"


@pytest.mark.asyncio
async def test_rejects_malformed_fit_with_stable_tagged_failure():
    result = await _call_tool(b"not a FIT payload")

    assert result["isError"] is True
    assert result["error_code"] == "FIT_DECODE_ERROR"
    assert result["availability"] == {
        "state": "unavailable",
        "reason": "fit_decode_error",
        "source": SOURCE,
    }


@pytest.mark.asyncio
async def test_rejects_structurally_invalid_payload_even_if_decoder_reports_no_warnings():
    _fit_module()
    with patch(
        "tp_mcp.tools.fit_timeseries._decode_fit_bytes",
        return_value=({}, []),
    ) as decode:
        result = await _call_tool(b"")

    assert result["isError"] is True
    assert result["error_code"] == "FIT_DECODE_ERROR"
    assert result["availability"]["reason"] == "fit_decode_error"
    decode.assert_not_called()


@pytest.mark.asyncio
async def test_accepts_structurally_valid_fit_with_no_activity_messages():
    result = await _call_tool(_encoded_empty_fit())

    assert "isError" not in result
    assert result["samples"] == []
    assert result["laps"] == []
    assert result["sessions"] == []
    assert result["availability"] == {
        "state": "available",
        "reason": "source_returned_no_samples",
        "source": SOURCE,
    }


@pytest.mark.asyncio
async def test_enforces_compressed_size_limit_before_decode(monkeypatch: pytest.MonkeyPatch):
    module = _fit_module()
    monkeypatch.setattr(module, "MAX_COMPRESSED_FIT_BYTES", 4)
    decode = AsyncMock(side_effect=AssertionError("decoder must not run"))
    monkeypatch.setattr(module, "_decode_fit_bytes", decode)

    result = await _call_tool(b"12345")

    assert result["error_code"] == "PAYLOAD_TOO_LARGE"
    assert result["availability"]["reason"] == "compressed_size_limit_exceeded"
    decode.assert_not_called()


@pytest.mark.asyncio
async def test_bounds_gzip_output_while_reading_before_decode(monkeypatch: pytest.MonkeyPatch):
    module = _fit_module()
    monkeypatch.setattr(module, "MAX_DECOMPRESSED_FIT_BYTES", 32)
    decode = AsyncMock(side_effect=AssertionError("decoder must not run"))
    monkeypatch.setattr(module, "_decode_fit_bytes", decode)

    result = await _call_tool(gzip.compress(b"x" * 64))

    assert result["error_code"] == "PAYLOAD_TOO_LARGE"
    assert result["availability"]["reason"] == "decompressed_size_limit_exceeded"
    decode.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(("offset", "limit"), [(-1, 500), (0, 0), (0, 1001)])
async def test_rejects_invalid_page_bounds(offset: int, limit: int):
    result = await _call_tool(_encoded_native_fit(), offset=offset, limit=limit)

    assert result["isError"] is True
    assert result["error_code"] == "VALIDATION_ERROR"
    assert result["availability"] == {
        "state": "unavailable",
        "reason": "validation_error",
        "source": SOURCE,
    }


@pytest.mark.asyncio
async def test_preserves_missing_file_error_and_adds_stable_availability_tag():
    module = _fit_module()
    tool = getattr(module, "tp_get_workout_file_timeseries", None)
    assert tool is not None
    legacy_error = {
        "isError": True,
        "error_code": "NOT_FOUND",
        "message": f"Workout file {FILE_ID} not found.",
    }
    with patch(
        "tp_mcp.tools.fit_timeseries._fetch_workout_file_bytes",
        new=AsyncMock(return_value=(None, legacy_error)),
    ):
        result = await tool(str(WORKOUT_ID), str(FILE_ID))

    assert result == {
        **legacy_error,
        "availability": {
            "state": "unavailable",
            "reason": "file_not_found",
            "source": SOURCE,
        },
    }


@pytest.mark.asyncio
async def test_sanitizes_arbitrary_upstream_fetch_error_details():
    module = _fit_module()
    tool = getattr(module, "tp_get_workout_file_timeseries", None)
    assert tool is not None
    upstream_error = {
        "isError": True,
        "error_code": "API_ERROR",
        "message": "GET https://signed.invalid/raw?email=rider@example.com failed at /private/tp/file.fit",
    }
    with patch(
        "tp_mcp.tools.fit_timeseries._fetch_workout_file_bytes",
        new=AsyncMock(return_value=(None, upstream_error)),
    ):
        result = await tool(str(WORKOUT_ID), str(FILE_ID))

    assert result["error_code"] == "API_ERROR"
    assert result["message"] == "Workout file could not be fetched."
    assert "signed.invalid" not in repr(result)
    assert "rider@example.com" not in repr(result)
    assert "/private/tp/file.fit" not in repr(result)


@pytest.mark.asyncio
async def test_raw_file_helper_returns_bytes_without_writing_to_disk():
    workout_files = import_module("tp_mcp.tools.workout_files")
    fetch = getattr(workout_files, "_fetch_workout_file_bytes", None)
    assert fetch is not None, "_fetch_workout_file_bytes must be implemented"
    client = AsyncMock()
    client.ensure_athlete_id = AsyncMock(return_value=123456)
    client.get_raw = AsyncMock(
        return_value=RawResponse(
            success=True,
            content=b"FIT bytes",
            content_type="application/octet-stream",
            content_disposition='attachment; filename="activity.fit.gz"',
        )
    )

    with patch("tp_mcp.tools.workout_files.TPClient") as client_type:
        client_type.return_value.__aenter__.return_value = client
        with patch("pathlib.Path.write_bytes", side_effect=AssertionError("must not write")):
            payload, metadata = await fetch(str(WORKOUT_ID), str(FILE_ID))

    assert payload == b"FIT bytes"
    assert metadata == {
        "workout_id": str(WORKOUT_ID),
        "file_id": str(FILE_ID),
        "file_name": "activity.fit.gz",
        "content_type": "application/octet-stream",
        "size_bytes": 9,
    }
    client.get_raw.assert_awaited_once_with(
        f"/fitness/v6/athletes/123456/workouts/{WORKOUT_ID}/rawfiledata/{FILE_ID}"
    )


@pytest.mark.asyncio
async def test_raw_file_helper_supports_bounded_streaming_fetch():
    workout_files = import_module("tp_mcp.tools.workout_files")
    fetch = getattr(workout_files, "_fetch_workout_file_bytes", None)
    assert fetch is not None
    client = AsyncMock()
    client.ensure_athlete_id = AsyncMock(return_value=123456)
    client.get_raw_bounded = AsyncMock(
        return_value=RawResponse(
            success=False,
            error_code=ErrorCode.PAYLOAD_TOO_LARGE,
            message="Raw response exceeds the configured size limit.",
        )
    )

    with patch("tp_mcp.tools.workout_files.TPClient") as client_type:
        client_type.return_value.__aenter__.return_value = client
        payload, result = await fetch(
            str(WORKOUT_ID),
            str(FILE_ID),
            max_bytes=16,
        )

    assert payload is None
    assert result["error_code"] == "PAYLOAD_TOO_LARGE"
    client.get_raw_bounded.assert_awaited_once_with(
        f"/fitness/v6/athletes/123456/workouts/{WORKOUT_ID}/rawfiledata/{FILE_ID}",
        max_bytes=16,
    )


@pytest.mark.asyncio
async def test_response_never_exposes_bytes_urls_email_or_paths():
    result = await _call_tool(_encoded_native_fit())
    result_text = repr(result).lower()

    assert "signed_url" not in result_text
    assert "saved_to" not in result_text
    assert "file_name" not in result_text
    assert "email" not in result_text
    assert "fit bytes" not in result_text
