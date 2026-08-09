"""Tools for workout analysis via the Peaksware analysis API."""

import logging
from typing import Any

import httpx
from pydantic import ValidationError

from tp_mcp.client import TPClient, parse_workout_analysis
from tp_mcp.tools._validation import WorkoutIdInput, format_validation_error
from tp_mcp.tools.analysis_contract import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    TimeSeriesPageInput,
    build_timeseries_page,
)

logger = logging.getLogger("tp-mcp")

ANALYSIS_API_BASE = "https://api.peakswaresb.com"
ANALYSIS_TIMEOUT = 60.0


async def _fetch_workout_analysis(
    workout_id: str,
) -> tuple[int | None, dict[str, Any]]:
    """Fetch raw workout analysis using the authenticated Peaksware endpoint."""
    try:
        validated = WorkoutIdInput(workout_id=workout_id)
    except (ValidationError, ValueError) as e:
        msg = format_validation_error(e) if isinstance(e, ValidationError) else str(e)
        return None, {
            "isError": True,
            "error_code": "VALIDATION_ERROR",
            "message": msg,
        }
    wid = validated.workout_id

    async with TPClient() as client:
        athlete_id = await client.ensure_athlete_id()
        if not athlete_id:
            return None, {
                "isError": True,
                "error_code": "AUTH_INVALID",
                "message": "Could not get athlete ID. Re-authenticate.",
            }

        token_result = await client._ensure_access_token()
        if not token_result.success:
            return None, {
                "isError": True,
                "error_code": "AUTH_INVALID",
                "message": token_result.message or "Failed to obtain access token.",
            }

        access_token = client._token_cache.access_token
        if not access_token:
            return None, {
                "isError": True,
                "error_code": "AUTH_INVALID",
                "message": "No access token available. Re-authenticate.",
            }

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/json",
            "Origin": "https://app.trainingpeaks.com",
            "Referer": "https://app.trainingpeaks.com/",
        }

        try:
            async with httpx.AsyncClient(timeout=ANALYSIS_TIMEOUT) as http_client:
                response = await http_client.post(
                    f"{ANALYSIS_API_BASE}/workout-analysis/v1/analyze",
                    headers=headers,
                    json={"workoutId": wid, "viewingPersonId": athlete_id},
                )
        except httpx.TimeoutException:
            return None, {
                "isError": True,
                "error_code": "NETWORK_ERROR",
                "message": "Analysis request timed out.",
            }
        except httpx.RequestError:
            logger.exception("Network error during workout analysis")
            return None, {
                "isError": True,
                "error_code": "NETWORK_ERROR",
                "message": "A network error occurred.",
            }

        if response.status_code == 401:
            return None, {
                "isError": True,
                "error_code": "AUTH_EXPIRED",
                "message": "Session expired. Run 'tp-mcp auth' to re-authenticate.",
            }
        if response.status_code == 404:
            return None, {
                "isError": True,
                "error_code": "NOT_FOUND",
                "message": f"Workout {workout_id} not found for analysis.",
            }
        if response.status_code != 200:
            return None, {
                "isError": True,
                "error_code": "API_ERROR",
                "message": f"Analysis API error: {response.status_code}",
            }

        try:
            raw_data = response.json()
        except Exception:
            return None, {
                "isError": True,
                "error_code": "API_ERROR",
                "message": "Failed to parse analysis response.",
            }

    return wid, raw_data


async def tp_analyze_workout(workout_id: str) -> dict[str, Any]:
    """Get detailed workout analysis including metrics, zones, and lap data.

    Args:
        workout_id: The workout ID (from tp_get_workouts).

    Returns:
        Dict with totals, data channels, lap data, and time-series access metadata.
    """
    wid, raw_data = await _fetch_workout_analysis(workout_id)
    if wid is None:
        return raw_data

    try:
        analysis = parse_workout_analysis(raw_data)
    except Exception:
        logger.exception("Failed to parse workout analysis")
        return {
            "isError": True,
            "error_code": "API_ERROR",
            "message": "Failed to parse workout analysis.",
        }

    totals = {t.name: {"value": t.value, "unit": t.unit} for t in analysis.totals}

    channels = [
        {
            k: v
            for k, v in {
                "identifier": ch.identifier,
                "name": ch.name,
                "unit": ch.unit,
                "min": ch.min,
                "max": ch.max,
                "average": ch.average,
                "zones": ch.zones,
            }.items()
            if v is not None
        }
        for ch in analysis.data_elements
    ]

    return {
        "workoutId": analysis.workout_id,
        "startTimestamp": analysis.start_timestamp,
        "stopTimestamp": analysis.stop_timestamp,
        "totals": totals,
        "dataChannels": channels,
        "lapData": analysis.lap_data,
        "lapColumns": analysis.lap_columns,
        "time_series_points": len(analysis.data),
        "time_series_access": {
            "tool": "tp_get_workout_timeseries",
            "workout_id": analysis.workout_id,
            "total_samples": len(analysis.data),
            "default_limit": DEFAULT_PAGE_LIMIT,
            "max_limit": MAX_PAGE_LIMIT,
        },
    }


async def tp_get_workout_timeseries(
    workout_id: str,
    offset: int = 0,
    limit: int = DEFAULT_PAGE_LIMIT,
    channels: list[str] | None = None,
    include_location: bool = False,
) -> dict[str, Any]:
    """Return an in-memory, paginated workout analysis time series."""
    try:
        page_input = TimeSeriesPageInput(
            offset=offset,
            limit=limit,
            channels=channels,
            include_location=include_location,
        )
    except (ValidationError, ValueError) as e:
        msg = format_validation_error(e) if isinstance(e, ValidationError) else str(e)
        return {
            "isError": True,
            "error_code": "VALIDATION_ERROR",
            "message": msg,
        }

    wid, raw_data = await _fetch_workout_analysis(workout_id)
    if wid is None:
        return raw_data

    try:
        analysis = parse_workout_analysis(raw_data)
    except Exception:
        logger.exception("Failed to parse workout analysis")
        return {
            "isError": True,
            "error_code": "API_ERROR",
            "message": "Failed to parse workout analysis.",
        }

    channel_metadata = [
        {
            "identifier": channel.identifier,
            "name": channel.name,
            "unit": channel.unit,
        }
        for channel in analysis.data_elements
    ]
    return build_timeseries_page(
        workout_id=analysis.workout_id,
        samples=analysis.data,
        channel_metadata=channel_metadata,
        start_timestamp=analysis.start_timestamp,
        stop_timestamp=analysis.stop_timestamp,
        offset=page_input.offset,
        limit=page_input.limit,
        requested_channels=page_input.channels,
        include_location=page_input.include_location,
        source="trainingpeaks_analysis",
    )
