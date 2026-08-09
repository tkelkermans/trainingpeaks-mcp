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

    assert result == error
