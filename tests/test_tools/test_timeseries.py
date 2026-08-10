"""Tests for hosted-safe TrainingPeaks analysis time-series access."""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from tp_mcp.tools import analyze

WORKOUT_ID = 3553733903


def _analysis_response(samples: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "workoutId": WORKOUT_ID,
        "startTimestamp": "2025-01-08T12:00:00",
        "stopTimestamp": "2025-01-08T13:00:00",
        "totals": [],
        "dataElements": [
            {
                "identifier": "Power",
                "name": "Power",
                "unit": "watts",
                "min": 0,
                "max": 800,
                "average": 200,
            },
            {
                "identifier": "HeartRate",
                "name": "Heart Rate",
                "unit": "bpm",
                "min": 80,
                "max": 185,
                "average": 145,
            },
            {
                "identifier": "Latitude",
                "name": "Latitude",
                "unit": "degrees",
            },
            {
                "identifier": "Longitude",
                "name": "Longitude",
                "unit": "degrees",
            },
        ],
        "data": samples
        if samples is not None
        else [
            {
                "time": 0,
                "Power": 150,
                "HeartRate": 120,
                "Latitude": 46.1,
                "Longitude": 7.1,
            },
            {
                "time": 4,
                "Power": 200,
                "HeartRate": 135,
                "Latitude": 46.2,
                "Longitude": 7.2,
            },
            {
                "time": 8,
                "Power": 220,
                "HeartRate": 145,
                "Latitude": 46.3,
                "Longitude": 7.3,
            },
        ],
        "lapData": [],
        "lapColumns": [],
    }


async def _call_timeseries(**kwargs: Any) -> dict[str, Any]:
    tool = getattr(analyze, "tp_get_workout_timeseries", None)
    assert tool is not None, "tp_get_workout_timeseries must be implemented"
    with patch(
        "tp_mcp.tools.analyze._fetch_workout_analysis",
        new=AsyncMock(return_value=(WORKOUT_ID, _analysis_response())),
        create=True,
    ):
        return await tool(str(WORKOUT_ID), **kwargs)


@pytest.mark.asyncio
async def test_returns_bounded_page_with_explicit_elapsed_time_contract():
    result = await _call_timeseries(limit=2)

    assert result["workout_id"] == WORKOUT_ID
    assert result["samples"] == [
        {"elapsed_seconds": 0, "Power": 150, "HeartRate": 120},
        {"elapsed_seconds": 4, "Power": 200, "HeartRate": 135},
    ]
    assert result["page"] == {
        "offset": 0,
        "limit": 2,
        "returned": 2,
        "total": 3,
        "has_more": True,
        "next_offset": 2,
    }
    assert result["timestamps"] == {
        "start": "2025-01-08T12:00:00",
        "stop": "2025-01-08T13:00:00",
        "timezone": None,
    }


@pytest.mark.asyncio
async def test_filters_channels_and_reports_units_provenance_and_availability():
    result = await _call_timeseries(channels=["Power"])

    assert result["samples"] == [
        {"elapsed_seconds": 0, "Power": 150},
        {"elapsed_seconds": 4, "Power": 200},
        {"elapsed_seconds": 8, "Power": 220},
    ]
    assert result["units"] == {"elapsed_seconds": "s", "Power": "watts"}
    assert result["channels"] == [
        {
            "identifier": "Power",
            "name": "Power",
            "unit": "watts",
            "source": "trainingpeaks_analysis",
            "available": True,
            "availability": {
                "state": "available",
                "reason": None,
                "source": "trainingpeaks_analysis",
            },
            "provenance": {
                "source": "trainingpeaks_analysis",
                "workout_id": WORKOUT_ID,
            },
        }
    ]
    assert result["availability"] == {
        "state": "available",
        "reason": None,
        "source": "trainingpeaks_analysis",
    }
    assert result["provenance"] == {
        "source": "trainingpeaks_analysis",
        "workout_id": WORKOUT_ID,
    }


@pytest.mark.asyncio
async def test_redacts_location_by_default_from_samples_inventory_and_units():
    result = await _call_timeseries()

    assert result["privacy"] == {
        "location_included": False,
        "redacted_fields": ["Latitude", "Longitude"],
    }
    assert all("Latitude" not in sample for sample in result["samples"])
    assert all("Longitude" not in sample for sample in result["samples"])
    assert {channel["identifier"] for channel in result["channels"]} == {
        "Power",
        "HeartRate",
    }
    assert "Latitude" not in result["units"]
    assert "Longitude" not in result["units"]


@pytest.mark.asyncio
async def test_redacts_coordinate_like_channel_name_variants():
    coordinate_names = [
        "gps_lat",
        "gps_lon",
        "start_position_lat",
        "end_position_long",
        "position_lat",
        "position_long",
        "latitude",
        "longitude",
    ]
    samples = [
        {
            "time": 0,
            "Power": 150,
            **{name: index for index, name in enumerate(coordinate_names)},
        }
    ]
    response = _analysis_response(samples)
    response["dataElements"].extend(
        {
            "identifier": name,
            "name": name,
            "unit": "degrees",
        }
        for name in coordinate_names
    )
    tool = getattr(analyze, "tp_get_workout_timeseries", None)
    assert tool is not None

    with patch(
        "tp_mcp.tools.analyze._fetch_workout_analysis",
        new=AsyncMock(return_value=(WORKOUT_ID, response)),
    ):
        result = await tool(str(WORKOUT_ID))

    assert result["samples"] == [{"elapsed_seconds": 0, "Power": 150}]
    assert set(result["privacy"]["redacted_fields"]) == {
        "Latitude",
        "Longitude",
        *coordinate_names,
    }
    assert not set(coordinate_names) & set(result["units"])
    assert not set(coordinate_names) & {
        channel["identifier"] for channel in result["channels"]
    }


@pytest.mark.asyncio
async def test_includes_location_only_with_explicit_opt_in():
    result = await _call_timeseries(include_location=True)

    assert result["samples"][0]["Latitude"] == 46.1
    assert result["samples"][0]["Longitude"] == 7.1
    assert result["privacy"] == {
        "location_included": True,
        "redacted_fields": [],
    }
    assert result["units"]["Latitude"] == "degrees"
    assert result["units"]["Longitude"] == "degrees"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("offset", "limit"),
    [(-1, 500), (0, 0), (0, 1001)],
)
async def test_rejects_out_of_bounds_page_inputs(offset: int, limit: int):
    result = await _call_timeseries(offset=offset, limit=limit)

    assert result["isError"] is True
    assert result["error_code"] == "VALIDATION_ERROR"
    assert result["availability"] == {
        "state": "unavailable",
        "reason": "validation_error",
        "source": "trainingpeaks_analysis",
    }


@pytest.mark.asyncio
async def test_tags_invalid_workout_id_as_validation_unavailable():
    result = await analyze.tp_get_workout_timeseries("not-a-workout-id")

    assert result["isError"] is True
    assert result["error_code"] == "VALIDATION_ERROR"
    assert result["availability"] == {
        "state": "unavailable",
        "reason": "validation_error",
        "source": "trainingpeaks_analysis",
    }


@pytest.mark.asyncio
async def test_reports_missing_requested_channel_with_stable_reason():
    result = await _call_timeseries(channels=["Cadence"])

    assert result["availability"] == {
        "state": "partial",
        "reason": "requested_channels_unavailable",
        "source": "trainingpeaks_analysis",
    }
    assert result["unavailable_channels"] == ["Cadence"]
    assert result["channels"] == [
        {
            "identifier": "Cadence",
            "requested_name": "Cadence",
            "name": "Cadence",
            "unit": None,
            "source": "trainingpeaks_analysis",
            "available": False,
            "availability": {
                "state": "unavailable",
                "reason": "channel_not_available",
                "source": "trainingpeaks_analysis",
            },
            "provenance": {
                "source": "trainingpeaks_analysis",
                "workout_id": WORKOUT_ID,
            },
        }
    ]


@pytest.mark.asyncio
async def test_elapsed_seconds_filter_keeps_mandatory_channel_metadata():
    result = await _call_timeseries(channels=["elapsed_seconds"])

    assert result["samples"] == [
        {"elapsed_seconds": 0},
        {"elapsed_seconds": 4},
        {"elapsed_seconds": 8},
    ]
    assert result["units"] == {"elapsed_seconds": "s"}
    assert result["channels"] == [
        {
            "identifier": "elapsed_seconds",
            "name": "Elapsed time",
            "unit": "s",
            "source": "trainingpeaks_analysis",
            "available": True,
            "availability": {
                "state": "available",
                "reason": None,
                "source": "trainingpeaks_analysis",
            },
            "provenance": {
                "source": "trainingpeaks_analysis",
                "workout_id": WORKOUT_ID,
            },
        }
    ]
    assert result["availability"] == {
        "state": "available",
        "reason": None,
        "source": "trainingpeaks_analysis",
    }


@pytest.mark.asyncio
async def test_paginates_all_957_samples_without_overlap_or_omission():
    samples = [{"time": index, "Power": index} for index in range(957)]
    tool = getattr(analyze, "tp_get_workout_timeseries", None)
    assert tool is not None, "tp_get_workout_timeseries must be implemented"
    fetch = AsyncMock(return_value=(WORKOUT_ID, _analysis_response(samples)))

    with patch(
        "tp_mcp.tools.analyze._fetch_workout_analysis",
        new=fetch,
        create=True,
    ):
        first = await tool(str(WORKOUT_ID), offset=0, limit=500)
        second = await tool(str(WORKOUT_ID), offset=500, limit=500)

    assert len(first["samples"]) == 500
    assert first["samples"][0]["elapsed_seconds"] == 0
    assert first["samples"][-1]["elapsed_seconds"] == 499
    assert first["page"]["next_offset"] == 500
    assert len(second["samples"]) == 457
    assert second["samples"][0]["elapsed_seconds"] == 500
    assert second["samples"][-1]["elapsed_seconds"] == 956
    assert second["page"]["has_more"] is False
    assert second["page"]["next_offset"] is None
    assert first["page"]["total"] == second["page"]["total"] == 957


@pytest.mark.asyncio
async def test_preserves_analysis_fetch_errors():
    tool = getattr(analyze, "tp_get_workout_timeseries", None)
    assert tool is not None, "tp_get_workout_timeseries must be implemented"
    error = {
        "isError": True,
        "error_code": "AUTH_EXPIRED",
        "message": "Session expired. Run 'tp-mcp auth' to re-authenticate.",
    }
    with patch(
        "tp_mcp.tools.analyze._fetch_workout_analysis",
        new=AsyncMock(return_value=(None, error)),
        create=True,
    ):
        result = await tool(str(WORKOUT_ID))

    assert result == {
        **error,
        "availability": {
            "state": "unavailable",
            "reason": "analysis_fetch_error",
            "source": "trainingpeaks_analysis",
        },
    }


@pytest.mark.asyncio
async def test_tags_analysis_parse_errors_as_unavailable():
    tool = getattr(analyze, "tp_get_workout_timeseries", None)
    assert tool is not None
    malformed = {**_analysis_response(), "workoutId": "not-an-integer"}

    with patch(
        "tp_mcp.tools.analyze._fetch_workout_analysis",
        new=AsyncMock(return_value=(WORKOUT_ID, malformed)),
    ):
        result = await tool(str(WORKOUT_ID))

    assert result == {
        "isError": True,
        "error_code": "API_ERROR",
        "message": "Failed to parse workout analysis.",
        "availability": {
            "state": "unavailable",
            "reason": "analysis_parse_error",
            "source": "trainingpeaks_analysis",
        },
    }
