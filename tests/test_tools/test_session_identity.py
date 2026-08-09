"""Decision-table coverage for read-only workout session classification."""

from copy import deepcopy
from unittest.mock import AsyncMock, call, patch

import pytest

from tp_mcp.tools.session_identity import tp_classify_sessions

GARMIN_ID = "3875883540"
TPV_ID = "3892963444"
APPLE_ID = "3892964243"


def _detail(
    workout_id: str,
    *,
    title: str,
    duration: float | None,
    tss: float | None,
    avg_power: float | None,
    normalized_power: float | None,
    avg_hr: float | None,
    avg_cadence: float | None,
    file_name: str,
    planned_duration: float | None = None,
    planned_structure: dict | None = None,
    source: str | None = None,
) -> dict:
    file_metadata = {
        "file_id": f"file-{workout_id}",
        "file_name": file_name,
    }
    if source is not None:
        file_metadata["source"] = source
    return {
        "id": workout_id,
        "date": "2026-08-09",
        "start_time": None,
        "title": title,
        "sport": "Bike",
        "metrics": {
            "duration_planned": planned_duration,
            "duration_actual": duration,
            "tss_planned": 22.0 if planned_duration is not None else None,
            "tss_actual": tss,
            "avg_power": avg_power,
            "normalized_power": normalized_power,
            "avg_hr": avg_hr,
            "avg_cadence": avg_cadence,
        },
        "completed": True,
        "structured_workout": planned_structure,
        "device_files": [file_metadata],
        "attachment_files": [],
    }


def _analysis(
    workout_id: str,
    *,
    start: str | None,
    laps: list[dict] | None = None,
    channels: list[dict] | None = None,
) -> dict:
    return {
        "workoutId": int(workout_id),
        "startTimestamp": start,
        "stopTimestamp": None,
        "totals": [],
        "dataElements": channels or [],
        "lapData": laps or [],
        "lapColumns": [],
        "time_series_points": 0,
    }


def _august_9_sources() -> tuple[dict[str, dict], dict[str, dict]]:
    structure = {"structure": [{"name": "Recovery", "length": 3000}]}
    details = {
        GARMIN_ID: _detail(
            GARMIN_ID,
            title="Return Recovery Spin 50min",
            duration=0.79636,
            tss=19.15,
            avg_power=143,
            normalized_power=144,
            avg_hr=119,
            avg_cadence=88,
            file_name=(
                "tp-3693769.2026-08-09-11-20-29-590Z."
                "GarminPing.AAAAAGp4Yn0cpxWm.FIT.gz"
            ),
            planned_duration=0.8333,
            planned_structure=structure,
            source="GarminPing",
        ),
        TPV_ID: _detail(
            TPV_ID,
            title="TrainingPeaks Virtual - Recovery Spin",
            duration=0.8625,
            tss=20.25,
            avg_power=137,
            normalized_power=142,
            avg_hr=117,
            avg_cadence=88,
            file_name="D0497FD51A72A2B3_20260809_102830_s.fit.gz",
        ),
        APPLE_ID: _detail(
            APPLE_ID,
            title="Indoor Cycling",
            duration=0.83111,
            tss=19.78,
            avg_power=142,
            normalized_power=143,
            avg_hr=118,
            avg_cadence=88,
            file_name="20260809_TPAppleHealth_indoor.fit.gz",
        ),
    }
    analyses = {
        GARMIN_ID: _analysis(
            GARMIN_ID,
            start="2026-08-09T10:31:35Z",
            laps=[{"Name": "Garmin lap"}],
        ),
        TPV_ID: _analysis(
            TPV_ID,
            start="2026-08-09T10:29:10Z",
            laps=[{"Name": "TP Virtual lap"}],
        ),
        APPLE_ID: _analysis(
            APPLE_ID,
            start="2026-08-09T10:29:26Z",
            laps=[{"Name": "Apple lap"}],
        ),
    }
    return details, analyses


async def _classify(
    details: dict[str, dict],
    analyses: dict[str, dict],
    workout_ids: list[str],
    *,
    preference: str = "auto",
) -> tuple[dict, AsyncMock, AsyncMock]:
    detail_fetch = AsyncMock(side_effect=lambda workout_id: deepcopy(details[workout_id]))
    analysis_fetch = AsyncMock(
        side_effect=lambda workout_id: (
            int(workout_id),
            deepcopy(analyses[workout_id]),
        )
    )
    with (
        patch("tp_mcp.tools.session_identity.tp_get_workout", detail_fetch),
        patch(
            "tp_mcp.tools.session_identity._fetch_workout_analysis",
            analysis_fetch,
        ),
    ):
        result = await tp_classify_sessions(workout_ids, preference=preference)
    return result, detail_fetch, analysis_fetch


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("preference", "execution_id", "tss_id", "tss_value"),
    [
        ("auto", TPV_ID, GARMIN_ID, 19.15),
        ("trainingpeaks_virtual", TPV_ID, TPV_ID, 20.25),
        ("garmin", GARMIN_ID, GARMIN_ID, 19.15),
    ],
)
async def test_august_9_cluster_uses_once_only_field_precedence(
    preference: str,
    execution_id: str,
    tss_id: str,
    tss_value: float,
):
    """Wrong provider precedence would double-count load or misassign plan/execution."""
    details, analyses = _august_9_sources()

    result, detail_fetch, analysis_fetch = await _classify(
        details,
        analyses,
        [GARMIN_ID, TPV_ID, APPLE_ID],
        preference=preference,
    )

    assert result["relationship"] == "same_session"
    assert result["relationship_reason"] == "all_candidates_complete_same_session"
    assert result["classification_policy"] == {
        "version": "1.0",
        "linkage": "complete",
        "max_candidates": 20,
        "same_start_max_seconds": 300,
        "distinct_start_min_seconds": 1200,
        "duration_match_max_seconds": 600,
        "duration_material_conflict_seconds": 1200,
    }
    assert result["availability"] == {
        "state": "available",
        "reason": None,
        "source": "trainingpeaks_session_classifier",
    }
    assert len(result["pairwise_evidence"]) == 3
    assert {
        pair["relationship"] for pair in result["pairwise_evidence"]
    } == {"same_session"}
    assert all(
        pair["evidence"]["policy_version"] == "1.0"
        and pair["evidence"]["thresholds"]
        == {
            "same_start_max_seconds": 300,
            "distinct_start_min_seconds": 1200,
            "duration_match_max_seconds": 600,
            "duration_material_conflict_seconds": 1200,
        }
        for pair in result["pairwise_evidence"]
    )
    assert result["clusters"][0]["member_workout_ids"] == [
        GARMIN_ID,
        TPV_ID,
        APPLE_ID,
    ]

    canonical = result["clusters"][0]["canonical_fields"]
    assert canonical["planned_duration"] == {
        "value": 0.8333,
        "unit": "h",
        "source_workout_id": GARMIN_ID,
        "method": "plan_anchor",
    }
    assert canonical["planned_structure"]["value"] == details[GARMIN_ID]["structured_workout"]
    assert canonical["planned_structure"]["source_workout_id"] == GARMIN_ID
    assert canonical["actual_duration"]["source_workout_id"] == execution_id
    assert canonical["laps"]["source_workout_id"] == execution_id
    assert canonical["actual_tss"] == {
        "value": tss_value,
        "unit": "TSS",
        "source_workout_id": tss_id,
        "method": (
            "plan_paired_device_preference"
            if preference == "auto"
            else "explicit_provider_preference"
        ),
    }
    assert canonical["average_power"]["source_workout_id"] == GARMIN_ID
    assert canonical["normalized_power"]["source_workout_id"] == GARMIN_ID
    assert canonical["average_heart_rate"]["source_workout_id"] == GARMIN_ID
    assert canonical["average_cadence"]["source_workout_id"] == GARMIN_ID
    assert sum(
        field["value"]
        for name, field in canonical.items()
        if name == "actual_tss"
    ) == tss_value

    roles = {
        member["workout_id"]: member["roles"] for member in result["members"]
    }
    assert "plan_anchor" in roles[GARMIN_ID]
    assert "physiology_auxiliary" in roles[GARMIN_ID]
    assert "execution" in roles[execution_id]
    expected_excluded = {GARMIN_ID, TPV_ID, APPLE_ID} - {
        GARMIN_ID,
        execution_id,
    }
    assert set(result["clusters"][0]["excluded_workout_ids"]) == expected_excluded
    for workout_id in expected_excluded:
        assert "duplicate_excluded" in roles[workout_id]

    expected_calls = [call(GARMIN_ID), call(TPV_ID), call(APPLE_ID)]
    assert detail_fetch.await_args_list == expected_calls
    assert analysis_fetch.await_args_list == expected_calls


@pytest.mark.asyncio
async def test_null_explicit_tss_falls_through_to_plan_paired_garmin():
    """Stopping on a preferred null would discard a valid once-only load value."""
    details, analyses = _august_9_sources()
    details[TPV_ID]["metrics"]["tss_actual"] = None

    result, _, _ = await _classify(
        details,
        analyses,
        [GARMIN_ID, TPV_ID, APPLE_ID],
        preference="trainingpeaks_virtual",
    )

    assert result["clusters"][0]["canonical_fields"]["actual_tss"] == {
        "value": 19.15,
        "unit": "TSS",
        "source_workout_id": GARMIN_ID,
        "method": "plan_paired_device_preference",
    }


@pytest.mark.asyncio
async def test_planned_duration_falls_through_independently_of_structure_anchor():
    """A structure-rich anchor with null duration must not hide another plan duration."""
    details, analyses = _august_9_sources()
    details[GARMIN_ID]["metrics"]["duration_planned"] = None
    details[TPV_ID]["metrics"]["duration_planned"] = 0.75

    result, _, _ = await _classify(
        details,
        analyses,
        [GARMIN_ID, TPV_ID, APPLE_ID],
    )

    canonical = result["clusters"][0]["canonical_fields"]
    assert canonical["planned_structure"]["source_workout_id"] == GARMIN_ID
    assert canonical["planned_structure"]["method"] == "plan_anchor"
    assert canonical["planned_duration"] == {
        "value": 0.75,
        "unit": "h",
        "source_workout_id": TPV_ID,
        "method": "planned_field_fallback",
    }


@pytest.mark.asyncio
async def test_planned_structure_falls_through_independently_of_duration_anchor():
    """A duration anchor with unusable structure must not hide another safe structure."""
    details, analyses = _august_9_sources()
    fallback_structure = {"structure": [{"name": "Fallback", "length": 2700}]}
    details[GARMIN_ID]["structured_workout"] = "/tmp/private-plan.json"
    details[TPV_ID]["structured_workout"] = fallback_structure
    details[TPV_ID]["metrics"]["duration_planned"] = None

    result, _, _ = await _classify(
        details,
        analyses,
        [GARMIN_ID, TPV_ID, APPLE_ID],
    )

    canonical = result["clusters"][0]["canonical_fields"]
    assert canonical["planned_duration"]["source_workout_id"] == GARMIN_ID
    assert canonical["planned_duration"]["method"] == "plan_anchor"
    assert canonical["planned_structure"] == {
        "value": fallback_structure,
        "unit": None,
        "source_workout_id": TPV_ID,
        "method": "planned_field_fallback",
    }


@pytest.mark.asyncio
async def test_physiology_falls_through_to_analysis_channel_average():
    """A null detail metric must not hide a field the member's analysis exposes."""
    details, analyses = _august_9_sources()
    details[GARMIN_ID]["metrics"]["avg_hr"] = None
    analyses[GARMIN_ID]["dataElements"] = [
        {
            "identifier": "HeartRate",
            "name": "Heart Rate",
            "unit": "bpm",
            "average": 119,
        }
    ]

    result, _, _ = await _classify(
        details,
        analyses,
        [GARMIN_ID, TPV_ID, APPLE_ID],
    )

    assert result["clusters"][0]["canonical_fields"]["average_heart_rate"] == {
        "value": 119,
        "unit": "bpm",
        "source_unit": "bpm",
        "source_workout_id": GARMIN_ID,
        "method": "plan_anchor_field_source",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source_value", "source_unit", "expected_value", "expected_conversion"),
    [
        (200, "W", 200, None),
        (0.2, "kW", 200, "kW_to_W"),
    ],
)
async def test_analysis_power_units_are_preserved_or_converted(
    source_value: float,
    source_unit: str,
    expected_value: float,
    expected_conversion: str | None,
):
    """Analysis fallback must not relabel noncanonical power values as watts."""
    details, analyses = _august_9_sources()
    for detail in details.values():
        detail["metrics"]["avg_power"] = None
    analyses[GARMIN_ID]["dataElements"] = [
        {
            "identifier": "Power",
            "name": "Power",
            "unit": source_unit,
            "average": source_value,
        }
    ]

    result, _, _ = await _classify(
        details,
        analyses,
        [GARMIN_ID, TPV_ID, APPLE_ID],
    )

    expected = {
        "value": expected_value,
        "unit": "W",
        "source_unit": source_unit,
        "source_workout_id": GARMIN_ID,
        "method": "plan_anchor_field_source",
    }
    if expected_conversion is not None:
        expected["conversion"] = expected_conversion
    assert result["clusters"][0]["canonical_fields"]["average_power"] == expected


@pytest.mark.asyncio
async def test_incompatible_analysis_metric_unit_is_withheld_with_evidence():
    """An incompatible source unit must not receive a false canonical label."""
    details, analyses = _august_9_sources()
    for detail in details.values():
        detail["metrics"]["avg_power"] = None
    analyses[GARMIN_ID]["dataElements"] = [
        {
            "identifier": "Power",
            "name": "Power",
            "unit": "bpm",
            "average": 200,
        }
    ]

    result, _, _ = await _classify(
        details,
        analyses,
        [GARMIN_ID, TPV_ID, APPLE_ID],
    )

    cluster = result["clusters"][0]
    assert "average_power" not in cluster["canonical_fields"]
    assert {
        "field": "average_power",
        "reason": "incompatible_source_unit",
        "candidates": [
            {
                "workout_id": GARMIN_ID,
                "value": 200,
                "source_unit": "bpm",
            }
        ],
    } in cluster["unresolved_fields"]


@pytest.mark.asyncio
async def test_public_members_and_laps_never_echo_unsafe_nested_metadata():
    """Removing lap redaction or member projection would leak private source values."""
    details, analyses = _august_9_sources()
    details[TPV_ID]["title"] = (
        "TrainingPeaks Virtual private@example.com /tmp/private-title.fit"
    )
    details[GARMIN_ID]["structured_workout"] = {
        "structure": [
            {
                "name": "Recovery",
                "length": 3000,
                "notes": "private@example.com /tmp/private-plan.fit",
                "gps_lat": 46.1,
            }
        ],
        "downloadUrl": "https://signed.example/private-plan-token",
    }
    analyses[TPV_ID]["lapData"] = [
        {
            "Name": "TP Virtual lap",
            "AveragePower": 137,
            "gps_lat": 46.1,
            "position_long": 7.1,
            "downloadUrl": "https://signed.example/private-token",
            "serverPath": "/tmp/private-lap.fit",
            "notes": "private@example.com Bearer opaque-secret",
        }
    ]

    result, _, _ = await _classify(
        details,
        analyses,
        [GARMIN_ID, TPV_ID, APPLE_ID],
    )

    assert all("title" not in member for member in result["members"])
    assert result["clusters"][0]["canonical_fields"]["laps"]["value"] == [
        {"Name": "TP Virtual lap", "AveragePower": 137}
    ]
    assert result["clusters"][0]["canonical_fields"]["planned_structure"][
        "value"
    ] == {"structure": [{"name": "Recovery", "length": 3000}]}
    serialized = str(result)
    assert "private@example.com" not in serialized
    assert "/tmp/private" not in serialized
    assert "signed.example" not in serialized
    assert "opaque-secret" not in serialized
    assert "gps_lat" not in serialized
    assert "position_long" not in serialized


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("second_start", "expected_relationship"),
    [
        ("2026-08-09T12:00:00Z", "distinct"),
        (None, "unresolved"),
    ],
)
async def test_distinct_and_unresolved_candidates_are_never_combined(
    second_start: str | None,
    expected_relationship: str,
):
    """Weak evidence must not create canonical metrics or duplicate exclusions."""
    details, analyses = _august_9_sources()
    result, _, _ = await _classify(
        details,
        {
            GARMIN_ID: analyses[GARMIN_ID],
            TPV_ID: _analysis(TPV_ID, start=second_start),
        },
        [GARMIN_ID, TPV_ID],
    )

    assert result["relationship"] == expected_relationship
    assert result["pairwise_evidence"][0]["relationship"] == expected_relationship
    assert all(cluster["canonical_fields"] == {} for cluster in result["clusters"])
    assert all(cluster["excluded_workout_ids"] == [] for cluster in result["clusters"])
    assert all(member["roles"] == [] for member in result["members"])


@pytest.mark.asyncio
async def test_complete_linkage_does_not_bridge_an_unresolved_pair():
    """Two close edges must not transitively merge a cluster whose third edge is weak."""
    details, analyses = _august_9_sources()
    analyses[GARMIN_ID]["startTimestamp"] = "2026-08-09T10:25:00Z"
    analyses[TPV_ID]["startTimestamp"] = "2026-08-09T10:29:00Z"
    analyses[APPLE_ID]["startTimestamp"] = "2026-08-09T10:33:00Z"

    result, _, _ = await _classify(
        details,
        analyses,
        [GARMIN_ID, TPV_ID, APPLE_ID],
    )

    relationships = {
        tuple(pair["workout_ids"]): pair["relationship"]
        for pair in result["pairwise_evidence"]
    }
    assert relationships[(GARMIN_ID, TPV_ID)] == "same_session"
    assert relationships[(TPV_ID, APPLE_ID)] == "same_session"
    assert relationships[(GARMIN_ID, APPLE_ID)] == "unresolved"
    assert result["relationship"] == "unresolved"
    assert result["clusters"][0]["canonical_fields"] == {}
    assert result["clusters"][0]["excluded_workout_ids"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("start_delta_seconds", "expected_relationship"),
    [
        (300, "same_session"),
        (1199, "unresolved"),
        (1200, "distinct"),
    ],
)
async def test_start_threshold_boundaries_are_explicit(
    start_delta_seconds: int,
    expected_relationship: str,
):
    """Off-by-one threshold changes would silently alter duplicate grouping."""
    details, analyses = _august_9_sources()
    details[TPV_ID]["metrics"]["duration_actual"] = details[GARMIN_ID]["metrics"][
        "duration_actual"
    ]
    minute, second = divmod(start_delta_seconds, 60)
    analyses[GARMIN_ID]["startTimestamp"] = "2026-08-09T10:00:00Z"
    analyses[TPV_ID]["startTimestamp"] = (
        f"2026-08-09T10:{minute:02d}:{second:02d}Z"
    )

    result, _, _ = await _classify(
        details,
        analyses,
        [GARMIN_ID, TPV_ID],
    )

    pair = result["pairwise_evidence"][0]
    assert pair["relationship"] == expected_relationship
    assert pair["evidence"]["start_delta_seconds"] == start_delta_seconds


@pytest.mark.asyncio
async def test_near_start_with_material_duration_conflict_is_unresolved():
    """A close start must not override materially incompatible ride durations."""
    details, analyses = _august_9_sources()
    details[GARMIN_ID]["metrics"]["duration_actual"] = 0.5
    details[TPV_ID]["metrics"]["duration_actual"] = 1.0

    result, _, _ = await _classify(
        details,
        analyses,
        [GARMIN_ID, TPV_ID],
    )

    pair = result["pairwise_evidence"][0]
    assert pair["relationship"] == "unresolved"
    assert pair["evidence"]["duration_delta_seconds"] == 1800
    assert "material_duration_conflict" in pair["evidence"]["signals"]
    assert result["clusters"][0]["canonical_fields"] == {}


@pytest.mark.asyncio
async def test_mixed_clusters_are_top_level_distinct_and_keep_input_order():
    """A same-session subset plus a distinct ride is not one canonical session."""
    details, analyses = _august_9_sources()
    analyses[APPLE_ID]["startTimestamp"] = "2026-08-09T12:00:00Z"
    requested = [TPV_ID, GARMIN_ID, APPLE_ID]

    result, _, _ = await _classify(details, analyses, requested)

    assert result["relationship"] == "distinct"
    assert result["relationship_reason"] == "candidates_partition_into_distinct_clusters"
    assert [member["workout_id"] for member in result["members"]] == requested
    assert result["clusters"][0]["member_workout_ids"] == [TPV_ID, GARMIN_ID]
    assert result["clusters"][0]["relationship"] == "same_session"
    assert result["clusters"][0]["canonical_fields"]
    assert result["clusters"][1] == {
        "relationship": "distinct",
        "member_workout_ids": [APPLE_ID],
        "canonical_fields": {},
        "unresolved_fields": [],
        "excluded_workout_ids": [],
    }


@pytest.mark.asyncio
async def test_material_tied_tss_conflict_is_withheld_and_reported():
    """A tied conflict must not be averaged or resolved by arbitrary input order."""
    details, analyses = _august_9_sources()
    first = details[TPV_ID]
    second = deepcopy(first)
    second["id"] = APPLE_ID
    second["title"] = "TrainingPeaks Virtual - second ingest"
    second["metrics"]["tss_actual"] = 35.0
    details = {TPV_ID: first, APPLE_ID: second}
    analyses = {
        TPV_ID: _analysis(TPV_ID, start="2026-08-09T10:29:10Z"),
        APPLE_ID: _analysis(APPLE_ID, start="2026-08-09T10:29:26Z"),
    }

    result, _, _ = await _classify(
        details,
        analyses,
        [TPV_ID, APPLE_ID],
        preference="trainingpeaks_virtual",
    )

    cluster = result["clusters"][0]
    assert "actual_tss" not in cluster["canonical_fields"]
    assert cluster["unresolved_fields"] == [
        {
            "field": "actual_tss",
            "reason": "material_tied_conflict",
            "candidates": [
                {"workout_id": TPV_ID, "value": 20.25},
                {"workout_id": APPLE_ID, "value": 35.0},
            ],
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_source", ["workout_detail", "workout_analysis"])
async def test_candidate_read_failure_is_stable_partial_unresolved(
    failed_source: str,
):
    """One unavailable read must not leak errors or permit a partial canonical merge."""
    details, analyses = _august_9_sources()
    detail_fetch = AsyncMock(side_effect=lambda workout_id: deepcopy(details[workout_id]))
    analysis_fetch = AsyncMock(
        side_effect=lambda workout_id: (int(workout_id), deepcopy(analyses[workout_id]))
    )
    if failed_source == "workout_detail":
        detail_fetch.side_effect = lambda workout_id: (
            {
                "isError": True,
                "error_code": "PRIVATE_/tmp/private-code",
                "message": (
                    "https://signed.example/private /tmp/private.fit "
                    "private@example.com"
                ),
            }
            if workout_id == TPV_ID
            else deepcopy(details[workout_id])
        )
    else:
        analysis_fetch.side_effect = lambda workout_id: (
            (
                None,
                {
                    "isError": True,
                    "error_code": "PRIVATE_/tmp/private-code",
                    "message": (
                        "https://signed.example/private /tmp/private.fit "
                        "private@example.com"
                    ),
                },
            )
            if workout_id == TPV_ID
            else (int(workout_id), deepcopy(analyses[workout_id]))
        )

    with (
        patch("tp_mcp.tools.session_identity.tp_get_workout", detail_fetch),
        patch(
            "tp_mcp.tools.session_identity._fetch_workout_analysis",
            analysis_fetch,
        ),
    ):
        result = await tp_classify_sessions([GARMIN_ID, TPV_ID])

    assert result["relationship"] == "unresolved"
    assert result["relationship_reason"] == "one_or_more_relationships_unresolved"
    assert result["availability"] == {
        "state": "partial",
        "reason": "candidate_source_unavailable",
        "source": "trainingpeaks_session_classifier",
    }
    assert result["source_errors"] == [
        {
            "workout_id": TPV_ID,
            "source": failed_source,
            "error_code": "API_ERROR",
            "reason": "candidate_source_unavailable",
        }
    ]
    assert result["pairwise_evidence"][0]["relationship"] == "unresolved"
    assert result["clusters"][0]["canonical_fields"] == {}
    assert result["clusters"][0]["excluded_workout_ids"] == []
    serialized = str(result)
    assert "signed.example" not in serialized
    assert "/tmp/private.fit" not in serialized
    assert "private@example.com" not in serialized


@pytest.mark.asyncio
@pytest.mark.parametrize("raised_source", ["workout_detail", "workout_analysis"])
async def test_candidate_read_exception_is_stable_partial_unresolved(
    raised_source: str,
):
    """A raised source exception must be isolated without leaking its text."""
    details, analyses = _august_9_sources()

    async def detail_fetch(workout_id: str) -> dict:
        if raised_source == "workout_detail" and workout_id == TPV_ID:
            raise RuntimeError(
                "https://signed.example/private /tmp/private.fit private@example.com"
            )
        return deepcopy(details[workout_id])

    async def analysis_fetch(workout_id: str) -> tuple[int, dict]:
        if raised_source == "workout_analysis" and workout_id == TPV_ID:
            raise RuntimeError(
                "Bearer opaque-secret C:\\Users\\private\\analysis.fit"
            )
        return int(workout_id), deepcopy(analyses[workout_id])

    detail_mock = AsyncMock(side_effect=detail_fetch)
    analysis_mock = AsyncMock(side_effect=analysis_fetch)
    with (
        patch("tp_mcp.tools.session_identity.tp_get_workout", detail_mock),
        patch(
            "tp_mcp.tools.session_identity._fetch_workout_analysis",
            analysis_mock,
        ),
    ):
        result = await tp_classify_sessions([GARMIN_ID, TPV_ID])

    assert result["relationship"] == "unresolved"
    assert result["availability"] == {
        "state": "partial",
        "reason": "candidate_source_unavailable",
        "source": "trainingpeaks_session_classifier",
    }
    assert result["source_errors"] == [
        {
            "workout_id": TPV_ID,
            "source": raised_source,
            "error_code": "API_ERROR",
            "reason": "candidate_source_unavailable",
        }
    ]
    assert all(cluster["canonical_fields"] == {} for cluster in result["clusters"])
    assert all(cluster["excluded_workout_ids"] == [] for cluster in result["clusters"])
    assert detail_mock.await_args_list == [call(GARMIN_ID), call(TPV_ID)]
    assert analysis_mock.await_args_list == [call(GARMIN_ID), call(TPV_ID)]
    serialized = str(result)
    for private_value in (
        "signed.example",
        "/tmp/private.fit",
        "private@example.com",
        "opaque-secret",
        r"C:\Users\private",
    ):
        assert private_value not in serialized


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("workout_ids", "preference"),
    [
        ([GARMIN_ID], "auto"),
        ([GARMIN_ID, "not-numeric"], "auto"),
        ([GARMIN_ID, GARMIN_ID], "auto"),
        ([GARMIN_ID, TPV_ID], "strava"),
        ([str(index) for index in range(1, 22)], "auto"),
        (["²", TPV_ID], "auto"),
        (["9" * 100, TPV_ID], "auto"),
    ],
)
async def test_rejects_invalid_ids_and_preferences(
    workout_ids: list[str],
    preference: str,
):
    """Invalid candidates must fail before any external read is attempted."""
    detail_fetch = AsyncMock()
    analysis_fetch = AsyncMock()
    with (
        patch("tp_mcp.tools.session_identity.tp_get_workout", detail_fetch),
        patch(
            "tp_mcp.tools.session_identity._fetch_workout_analysis",
            analysis_fetch,
        ),
    ):
        result = await tp_classify_sessions(workout_ids, preference=preference)

    assert result["isError"] is True
    assert result["error_code"] == "VALIDATION_ERROR"
    detail_fetch.assert_not_awaited()
    analysis_fetch.assert_not_awaited()
