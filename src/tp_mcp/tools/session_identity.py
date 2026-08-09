"""Conservative, read-only classification of TrainingPeaks workout copies."""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from itertools import combinations
from typing import Any, Literal

from tp_mcp.client import parse_workout_analysis
from tp_mcp.tools.analysis_contract import is_location_field
from tp_mcp.tools.analyze import _fetch_workout_analysis
from tp_mcp.tools.workouts import tp_get_workout

Preference = Literal["auto", "trainingpeaks_virtual", "garmin"]
Relationship = Literal["same_session", "distinct", "unresolved"]

CLASSIFIER_SOURCE = "trainingpeaks_session_classifier"
POLICY_VERSION = "1.0"
MAX_CANDIDATES = 20
SAME_START_MAX_SECONDS = 300
DISTINCT_START_MIN_SECONDS = 1200
DURATION_MATCH_MAX_SECONDS = 600
DURATION_MATERIAL_CONFLICT_SECONDS = 1200

_POLICY = {
    "version": POLICY_VERSION,
    "linkage": "complete",
    "max_candidates": MAX_CANDIDATES,
    "same_start_max_seconds": SAME_START_MAX_SECONDS,
    "distinct_start_min_seconds": DISTINCT_START_MIN_SECONDS,
    "duration_match_max_seconds": DURATION_MATCH_MAX_SECONDS,
    "duration_material_conflict_seconds": DURATION_MATERIAL_CONFLICT_SECONDS,
}
_THRESHOLDS = {
    key: value
    for key, value in _POLICY.items()
    if key.endswith("_seconds")
}
_ROLE_ORDER = (
    "plan_anchor",
    "execution",
    "physiology_auxiliary",
    "duplicate_excluded",
)
_SAFE_LAP_FIELDS = {
    "id",
    "lapnumber",
    "name",
    "starttime",
    "stoptime",
    "duration",
    "totaltime",
    "totalelapsedtime",
    "totaltimertime",
    "distance",
    "averagepower",
    "normalizedpower",
    "averageheartrate",
    "maxheartrate",
    "averagecadence",
    "maxcadence",
    "tss",
    "if",
    "intensityfactor",
    "calories",
    "elevationgain",
}
_SENSITIVE_KEY_PARTS = (
    "authorization",
    "cookie",
    "credential",
    "email",
    "password",
    "path",
    "secret",
    "serial",
    "token",
    "url",
)
_UNSAFE_STRING = re.compile(
    r"(?:https?://|\bBearer\s+|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?:^|\s)/\S+)",
    re.IGNORECASE,
)
_SAFE_LABEL = re.compile(r"^[\w .()_-]{1,100}$")
_DURATION_TEXT = re.compile(r"^\d{1,3}:\d{2}(?::\d{2}(?:\.\d+)?)?$")
_DROP = object()
_SAFE_ERROR_CODES = {
    "API_ERROR",
    "AUTH_EXPIRED",
    "AUTH_INVALID",
    "NETWORK_ERROR",
    "NOT_FOUND",
    "VALIDATION_ERROR",
}


@dataclass
class _Candidate:
    workout_id: str
    detail: dict[str, Any]
    analysis: dict[str, Any]
    detail_available: bool
    analysis_available: bool
    provider: str
    provider_evidence: list[dict[str, str]]
    roles: set[str] = field(default_factory=set)

    @property
    def metrics(self) -> dict[str, Any]:
        metrics = self.detail.get("metrics")
        return metrics if isinstance(metrics, dict) else {}

    @property
    def start_time(self) -> str | None:
        analysis_start = self.analysis.get("startTimestamp")
        if isinstance(analysis_start, str) and _parse_timestamp(analysis_start) is not None:
            return analysis_start
        detail_start = self.detail.get("start_time")
        if isinstance(detail_start, str) and _parse_timestamp(detail_start) is not None:
            return detail_start
        return None

    @property
    def actual_duration(self) -> float | None:
        return _as_float(self.metrics.get("duration_actual"))

    def actual_metric(self, name: str) -> float | None:
        detail_value = _as_float(self.metrics.get(name))
        if detail_value is not None:
            return detail_value
        channel_names = {
            "avg_power": {"power", "averagepower"},
            "avg_hr": {"heartrate", "averageheartrate"},
            "avg_cadence": {"cadence", "averagecadence"},
        }
        expected_channels = channel_names.get(name, set())
        channels = self.analysis.get("dataChannels")
        if isinstance(channels, list):
            for channel in channels:
                if not isinstance(channel, dict):
                    continue
                identifiers = {
                    _normalized_text(channel.get("identifier")),
                    _normalized_text(channel.get("name")),
                }
                if identifiers & expected_channels:
                    average = _as_float(channel.get("average"))
                    if average is not None:
                        return average
        total_names = {
            "normalized_power": {"np", "normalizedpower"},
            "tss_actual": {"tss", "trainingstressscore"},
        }
        expected_totals = total_names.get(name, set())
        totals = self.analysis.get("totals")
        if isinstance(totals, dict):
            for total_name, total in totals.items():
                if _normalized_text(total_name) not in expected_totals:
                    continue
                raw_value = total.get("value") if isinstance(total, dict) else total
                total_value = _as_float(raw_value)
                if total_value is not None:
                    return total_value
        return None

    @property
    def laps(self) -> list[dict[str, Any]] | None:
        laps = self.analysis.get("lapData")
        if not isinstance(laps, list) or not laps:
            return None
        safe_laps = [
            safe_lap
            for lap in laps
            if isinstance(lap, dict)
            if (safe_lap := _safe_lap(lap))
        ]
        return safe_laps or None


def _validation_error(message: str) -> dict[str, Any]:
    return {
        "isError": True,
        "error_code": "VALIDATION_ERROR",
        "message": message,
        "availability": {
            "state": "unavailable",
            "reason": "validation_error",
            "source": CLASSIFIER_SOURCE,
        },
    }


def _safe_error_code(value: Any) -> str:
    return value if isinstance(value, str) and value in _SAFE_ERROR_CODES else "API_ERROR"


def _validate_inputs(
    workout_ids: list[str | int],
    preference: str,
) -> tuple[list[str] | None, dict[str, Any] | None]:
    if preference not in {"auto", "trainingpeaks_virtual", "garmin"}:
        return None, _validation_error(
            "preference must be auto, trainingpeaks_virtual, or garmin."
        )
    if not isinstance(workout_ids, list):
        return None, _validation_error("workout_ids must be a list.")
    if not 2 <= len(workout_ids) <= MAX_CANDIDATES:
        return None, _validation_error(
            f"workout_ids must contain between 2 and {MAX_CANDIDATES} IDs."
        )

    normalized: list[str] = []
    for value in workout_ids:
        if isinstance(value, bool):
            return None, _validation_error("workout IDs must be positive integers.")
        text = str(value).strip()
        if not text.isdigit() or int(text) <= 0:
            return None, _validation_error("workout IDs must be positive integers.")
        canonical = str(int(text))
        if canonical in normalized:
            return None, _validation_error("workout IDs must be unique.")
        normalized.append(canonical)
    return normalized, None


def _normalized_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(character for character in value.casefold() if character.isalnum())


def _safe_nested_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) > 500 or _UNSAFE_STRING.search(value):
            return _DROP
        return value
    if isinstance(value, list):
        return [
            safe_value
            for item in value
            if (safe_value := _safe_nested_value(item)) is not _DROP
        ]
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                continue
            normalized_key = _normalized_text(key)
            if is_location_field(key) or any(
                part in normalized_key for part in _SENSITIVE_KEY_PARTS
            ):
                continue
            safe_value = _safe_nested_value(item)
            if safe_value is not _DROP:
                safe[key] = safe_value
        return safe
    return _DROP


def _safe_lap(lap: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in lap.items():
        normalized_key = _normalized_text(key)
        if normalized_key not in _SAFE_LAP_FIELDS:
            continue
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            safe[key] = value
        elif not isinstance(value, str) or _UNSAFE_STRING.search(value):
            continue
        elif normalized_key in {"starttime", "stoptime"}:
            if _parse_timestamp(value) is not None:
                safe[key] = value
        elif normalized_key in {
            "duration",
            "totaltime",
            "totalelapsedtime",
            "totaltimertime",
        }:
            if _DURATION_TEXT.fullmatch(value):
                safe[key] = value
        elif normalized_key in {"id", "name"} and _SAFE_LABEL.fullmatch(value):
            safe[key] = value
    return safe


def _matched_provider(value: Any) -> str | None:
    normalized = _normalized_text(value)
    if not normalized:
        return None
    if "tpapplehealth" in normalized or "applehealth" in normalized or "healthkit" in normalized:
        return "apple_health"
    if "garminping" in normalized or "garmin" in normalized:
        return "garmin"
    if "trainingpeaksvirtual" in normalized or "tpvirtual" in normalized:
        return "trainingpeaks_virtual"
    return None


def _detect_provider(detail: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
    evidence: list[dict[str, str]] = []
    metadata_matches: set[str] = set()
    for collection_name in ("device_files", "attachment_files"):
        items = detail.get(collection_name)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            for field_name in (
                "file_name",
                "source",
                "device_name",
                "manufacturer",
                "product",
            ):
                provider = _matched_provider(item.get(field_name))
                if provider is None:
                    continue
                metadata_matches.add(provider)
                evidence.append({
                    "source": f"{collection_name}.{field_name}",
                    "matched_provider": provider,
                })

    if len(metadata_matches) == 1:
        return next(iter(metadata_matches)), evidence
    if len(metadata_matches) > 1:
        return "unknown", evidence

    title_provider = _matched_provider(detail.get("title"))
    if title_provider is not None:
        evidence.append({
            "source": "title",
            "matched_provider": title_provider,
        })
        return title_provider, evidence
    return "unknown", evidence


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _parse_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return None


def _timestamp_delta_seconds(first: str | None, second: str | None) -> int | None:
    first_time = _parse_timestamp(first)
    second_time = _parse_timestamp(second)
    if first_time is None or second_time is None:
        return None
    if (first_time.tzinfo is None) != (second_time.tzinfo is None):
        return None
    return round(abs((first_time - second_time).total_seconds()))


def _duration_delta_seconds(first: float | None, second: float | None) -> int | None:
    if first is None or second is None:
        return None
    return round(abs(first - second) * 3600)


def _pair_relationship(
    first: _Candidate,
    second: _Candidate,
) -> tuple[Relationship, dict[str, Any]]:
    start_delta = _timestamp_delta_seconds(first.start_time, second.start_time)
    duration_delta = _duration_delta_seconds(
        first.actual_duration,
        second.actual_duration,
    )
    signals: list[str] = []

    first_sport = first.detail.get("sport")
    second_sport = second.detail.get("sport")
    sport_conflict = bool(
        first_sport
        and second_sport
        and str(first_sport).casefold() != str(second_sport).casefold()
    )
    if not first.detail_available or not second.detail_available:
        signals.append("workout_detail_unavailable")
    if not first.analysis_available or not second.analysis_available:
        signals.append("workout_analysis_unavailable")
    if sport_conflict:
        signals.append("sport_conflict")
    if start_delta is None:
        signals.append("start_time_unavailable_or_incomparable")
    elif start_delta <= SAME_START_MAX_SECONDS:
        signals.append("start_within_same_threshold")
    elif start_delta >= DISTINCT_START_MIN_SECONDS:
        signals.append("start_beyond_distinct_threshold")
    else:
        signals.append("start_between_thresholds")
    if duration_delta is None:
        signals.append("actual_duration_unavailable")
    elif duration_delta <= DURATION_MATCH_MAX_SECONDS:
        signals.append("duration_compatible")
    elif duration_delta >= DURATION_MATERIAL_CONFLICT_SECONDS:
        signals.append("material_duration_conflict")
    else:
        signals.append("duration_between_thresholds")

    sources_available = (
        first.detail_available
        and first.analysis_available
        and second.detail_available
        and second.analysis_available
    )
    if not sources_available:
        relationship: Relationship = "unresolved"
    elif sport_conflict or (
        start_delta is not None and start_delta >= DISTINCT_START_MIN_SECONDS
    ):
        relationship = "distinct"
    elif (
        start_delta is not None
        and start_delta <= SAME_START_MAX_SECONDS
        and duration_delta is not None
        and duration_delta <= DURATION_MATCH_MAX_SECONDS
    ):
        relationship = "same_session"
    else:
        relationship = "unresolved"

    return relationship, {
        "policy_version": POLICY_VERSION,
        "thresholds": dict(_THRESHOLDS),
        "providers": {
            first.workout_id: first.provider,
            second.workout_id: second.provider,
        },
        "start_times": {
            first.workout_id: first.start_time,
            second.workout_id: second.start_time,
        },
        "start_delta_seconds": start_delta,
        "actual_durations_hours": {
            first.workout_id: first.actual_duration,
            second.workout_id: second.actual_duration,
        },
        "duration_delta_seconds": duration_delta,
        "signals": signals,
    }


def _richness(candidate: _Candidate) -> int:
    actual_fields = (
        "duration_actual",
        "tss_actual",
        "avg_power",
        "normalized_power",
        "avg_hr",
        "avg_cadence",
    )
    score = sum(
        (
            candidate.actual_duration is not None
            if name == "duration_actual"
            else candidate.actual_metric(name) is not None
        )
        for name in actual_fields
    )
    return score + int(candidate.laps is not None)


def _field(
    value: Any,
    unit: str | None,
    candidate: _Candidate,
    method: str,
) -> dict[str, Any]:
    return {
        "value": value,
        "unit": unit,
        "source_workout_id": candidate.workout_id,
        "method": method,
    }


def _metric_getter(name: str) -> Callable[[_Candidate], Any]:
    def get_metric(candidate: _Candidate) -> Any:
        return candidate.metrics.get(name)

    return get_metric


def _actual_metric_getter(name: str) -> Callable[[_Candidate], float | None]:
    def get_actual_metric(candidate: _Candidate) -> float | None:
        return candidate.actual_metric(name)

    return get_actual_metric


def _planned_structure(candidate: _Candidate) -> Any:
    safe_value = _safe_nested_value(candidate.detail.get("structured_workout"))
    return None if safe_value is _DROP else safe_value


def _actual_duration(candidate: _Candidate) -> float | None:
    return candidate.actual_duration


def _laps(candidate: _Candidate) -> list[dict[str, Any]] | None:
    return candidate.laps


def _material_conflict(values: list[Any], tolerance: float) -> bool:
    if len(values) < 2:
        return False
    if all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
        numeric = [float(value) for value in values]
        return max(numeric) - min(numeric) > tolerance
    return any(value != values[0] for value in values[1:])


def _choose(
    candidates: list[_Candidate],
    *,
    field_name: str,
    value: Callable[[_Candidate], Any],
    rank: Callable[[_Candidate], tuple[int, ...]],
    tolerance: float,
    unresolved_fields: list[dict[str, Any]],
) -> _Candidate | None:
    available = [candidate for candidate in candidates if value(candidate) is not None]
    if not available:
        return None
    best_rank = max(rank(candidate) for candidate in available)
    tied = [candidate for candidate in available if rank(candidate) == best_rank]
    tied_values = [value(candidate) for candidate in tied]
    if _material_conflict(tied_values, tolerance):
        unresolved_fields.append({
            "field": field_name,
            "reason": "material_tied_conflict",
            "candidates": [
                {"workout_id": candidate.workout_id, "value": value(candidate)}
                for candidate in tied
            ],
        })
        return None
    return tied[0]


def _execution_rank(candidate: _Candidate, preference: Preference) -> tuple[int, int]:
    if preference != "auto" and candidate.provider == preference:
        provider_rank = 3
    elif candidate.provider == "trainingpeaks_virtual":
        provider_rank = 2
    else:
        provider_rank = 1
    return provider_rank, _richness(candidate)


def _execution_method(candidate: _Candidate, preference: Preference) -> str:
    if preference != "auto" and candidate.provider == preference:
        return "explicit_provider_preference"
    if candidate.provider == "trainingpeaks_virtual":
        return "trainingpeaks_virtual_preference"
    return "richest_actual_fallback"


def _plan_anchor(candidates: list[_Candidate]) -> tuple[_Candidate | None, list[_Candidate]]:
    planned = [
        candidate
        for candidate in candidates
        if candidate.metrics.get("duration_planned") is not None
        or candidate.metrics.get("tss_planned") is not None
        or candidate.detail.get("structured_workout") is not None
    ]
    if not planned:
        return None, []

    def rank(candidate: _Candidate) -> tuple[int, int, int, int, int]:
        return (
            int(candidate.detail.get("structured_workout") is not None),
            int(candidate.metrics.get("duration_planned") is not None),
            int(candidate.metrics.get("tss_planned") is not None),
            int(candidate.provider == "garmin"),
            _richness(candidate),
        )

    best_rank = max(rank(candidate) for candidate in planned)
    tied = [candidate for candidate in planned if rank(candidate) == best_rank]
    return tied[0], tied


def _physiology_rank(
    candidate: _Candidate,
    plan_anchor: _Candidate | None,
    execution_ids: set[str],
) -> tuple[int, int]:
    if plan_anchor is not None and candidate.workout_id == plan_anchor.workout_id:
        return 3, _richness(candidate)
    if candidate.workout_id in execution_ids:
        return 2, _richness(candidate)
    return 1, _richness(candidate)


def _tss_rank(
    candidate: _Candidate,
    preference: Preference,
    plan_anchor: _Candidate | None,
) -> tuple[int, int]:
    if preference != "auto" and candidate.provider == preference:
        return 3, _richness(candidate)
    if (
        plan_anchor is not None
        and candidate.workout_id == plan_anchor.workout_id
        and (
            candidate.provider == "garmin"
            or bool(candidate.detail.get("device_files"))
        )
    ):
        return 2, _richness(candidate)
    return 1, _richness(candidate)


def _tss_method(
    candidate: _Candidate,
    preference: Preference,
    plan_anchor: _Candidate | None,
) -> str:
    if preference != "auto" and candidate.provider == preference:
        return "explicit_provider_preference"
    if plan_anchor is not None and candidate.workout_id == plan_anchor.workout_id:
        return "plan_paired_device_preference"
    return "richest_actual_fallback"


def _canonicalize(
    candidates: list[_Candidate],
    preference: Preference,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    canonical: dict[str, Any] = {}
    unresolved_fields: list[dict[str, Any]] = []
    contributors: set[str] = set()
    anchor, tied_anchors = _plan_anchor(candidates)
    if anchor is not None:
        anchor.roles.add("plan_anchor")
        planned_values = (
            ("planned_duration", "duration_planned", "h", 1 / 60),
            ("planned_structure", "structured_workout", None, 0.0),
        )
        for output_name, source_name, unit, tolerance in planned_values:
            plan_getter = (
                _planned_structure
                if source_name == "structured_workout"
                else _metric_getter(source_name)
            )
            selected = _choose(
                tied_anchors,
                field_name=output_name,
                value=plan_getter,
                rank=lambda candidate: (0,),
                tolerance=tolerance,
                unresolved_fields=unresolved_fields,
            )
            if selected is not None:
                canonical[output_name] = _field(
                    plan_getter(selected),
                    unit,
                    selected,
                    "plan_anchor",
                )
                contributors.add(selected.workout_id)

    execution_ids: set[str] = set()
    execution_fields: tuple[
        tuple[str, Callable[[_Candidate], Any], str | None, float], ...
    ] = (
        ("actual_duration", _actual_duration, "h", 1 / 60),
        ("laps", _laps, None, 0.0),
    )
    for output_name, execution_getter, unit, tolerance in execution_fields:
        selected = _choose(
            candidates,
            field_name=output_name,
            value=execution_getter,
            rank=lambda candidate: _execution_rank(candidate, preference),
            tolerance=tolerance,
            unresolved_fields=unresolved_fields,
        )
        if selected is not None:
            selected.roles.add("execution")
            execution_ids.add(selected.workout_id)
            contributors.add(selected.workout_id)
            canonical[output_name] = _field(
                execution_getter(selected),
                unit,
                selected,
                _execution_method(selected, preference),
            )

    physiology_fields = (
        ("average_power", "avg_power", "W", 2.0),
        ("normalized_power", "normalized_power", "W", 2.0),
        ("average_heart_rate", "avg_hr", "bpm", 2.0),
        ("average_cadence", "avg_cadence", "rpm", 2.0),
    )
    for output_name, source_name, unit, tolerance in physiology_fields:
        physiology_getter = _actual_metric_getter(source_name)
        selected = _choose(
            candidates,
            field_name=output_name,
            value=physiology_getter,
            rank=lambda candidate: _physiology_rank(
                candidate,
                anchor,
                execution_ids,
            ),
            tolerance=tolerance,
            unresolved_fields=unresolved_fields,
        )
        if selected is not None:
            selected.roles.add("physiology_auxiliary")
            contributors.add(selected.workout_id)
            canonical[output_name] = _field(
                physiology_getter(selected),
                unit,
                selected,
                (
                    "plan_anchor_field_source"
                    if anchor is not None
                    and selected.workout_id == anchor.workout_id
                    else "available_field_precedence"
                ),
            )

    tss_getter = _actual_metric_getter("tss_actual")
    tss_source = _choose(
        candidates,
        field_name="actual_tss",
        value=tss_getter,
        rank=lambda candidate: _tss_rank(candidate, preference, anchor),
        tolerance=0.5,
        unresolved_fields=unresolved_fields,
    )
    if tss_source is not None:
        contributors.add(tss_source.workout_id)
        canonical["actual_tss"] = _field(
            tss_getter(tss_source),
            "TSS",
            tss_source,
            _tss_method(tss_source, preference, anchor),
        )

    excluded = [
        candidate.workout_id
        for candidate in candidates
        if candidate.workout_id not in contributors
    ]
    for candidate in candidates:
        if candidate.workout_id in excluded:
            candidate.roles.add("duplicate_excluded")
    return canonical, unresolved_fields, excluded


def _components(
    candidates: list[_Candidate],
    pair_relationships: dict[tuple[int, int], Relationship],
) -> list[list[int]]:
    remaining = set(range(len(candidates)))
    components: list[list[int]] = []
    while remaining:
        start = min(remaining)
        pending = [start]
        component: set[int] = set()
        while pending:
            current = pending.pop()
            if current in component:
                continue
            component.add(current)
            remaining.discard(current)
            for other in range(len(candidates)):
                if other == current or other in component:
                    continue
                pair = (min(current, other), max(current, other))
                if pair_relationships.get(pair) != "distinct":
                    pending.append(other)
        components.append(sorted(component))
    return components


def _component_relationship(
    indices: list[int],
    pair_relationships: dict[tuple[int, int], Relationship],
) -> Relationship:
    if len(indices) == 1:
        return "distinct"
    relationships = {
        pair_relationships[(first, second)]
        for first, second in combinations(indices, 2)
    }
    return "same_session" if relationships == {"same_session"} else "unresolved"


def _public_member(candidate: _Candidate) -> dict[str, Any]:
    raw_sport = candidate.detail.get("sport")
    safe_sport = (
        raw_sport
        if isinstance(raw_sport, str) and _SAFE_LABEL.fullmatch(raw_sport)
        else None
    )
    return {
        "workout_id": candidate.workout_id,
        "sport": safe_sport,
        "provider": candidate.provider,
        "provider_evidence": candidate.provider_evidence,
        "start_time": candidate.start_time,
        "source_availability": {
            "workout_detail": candidate.detail_available,
            "workout_analysis": candidate.analysis_available,
        },
        "roles": [role for role in _ROLE_ORDER if role in candidate.roles],
    }


async def tp_classify_sessions(
    workout_ids: list[str | int],
    preference: Preference = "auto",
) -> dict[str, Any]:
    """Classify likely workout copies without mutating TrainingPeaks state."""
    normalized_ids, validation_error = _validate_inputs(workout_ids, preference)
    if validation_error is not None or normalized_ids is None:
        return validation_error or _validation_error("Invalid input.")

    candidates: list[_Candidate] = []
    source_errors: list[dict[str, str]] = []
    for workout_id in normalized_ids:
        detail_result = await tp_get_workout(workout_id)
        detail_available = not bool(detail_result.get("isError"))
        detail = detail_result if detail_available else {}
        if not detail_available:
            source_errors.append({
                "workout_id": workout_id,
                "source": "workout_detail",
                "error_code": _safe_error_code(detail_result.get("error_code")),
                "reason": "candidate_source_unavailable",
            })

        analysis_id, raw_analysis = await _fetch_workout_analysis(workout_id)
        analysis_available = analysis_id is not None
        analysis: dict[str, Any] = {}
        if analysis_available:
            try:
                parsed = parse_workout_analysis(raw_analysis)
                analysis = {
                    "startTimestamp": parsed.start_timestamp,
                    "stopTimestamp": parsed.stop_timestamp,
                    "lapData": parsed.lap_data,
                    "totals": {
                        total.name: {"value": total.value, "unit": total.unit}
                        for total in parsed.totals
                    },
                    "dataChannels": [
                        {
                            "identifier": channel.identifier,
                            "name": channel.name,
                            "unit": channel.unit,
                            "average": channel.average,
                        }
                        for channel in parsed.data_elements
                    ],
                }
            except Exception:
                analysis_available = False
                raw_analysis = {"error_code": "API_ERROR"}
        if not analysis_available:
            source_errors.append({
                "workout_id": workout_id,
                "source": "workout_analysis",
                "error_code": _safe_error_code(raw_analysis.get("error_code")),
                "reason": "candidate_source_unavailable",
            })

        provider, provider_evidence = _detect_provider(detail)
        candidates.append(_Candidate(
            workout_id=workout_id,
            detail=detail,
            analysis=analysis,
            detail_available=detail_available,
            analysis_available=analysis_available,
            provider=provider,
            provider_evidence=provider_evidence,
        ))

    pairwise_evidence: list[dict[str, Any]] = []
    pair_relationships: dict[tuple[int, int], Relationship] = {}
    for first_index, second_index in combinations(range(len(candidates)), 2):
        first = candidates[first_index]
        second = candidates[second_index]
        relationship, evidence = _pair_relationship(first, second)
        pair_relationships[(first_index, second_index)] = relationship
        pairwise_evidence.append({
            "workout_ids": [first.workout_id, second.workout_id],
            "relationship": relationship,
            "evidence": evidence,
        })

    clusters: list[dict[str, Any]] = []
    for indices in _components(candidates, pair_relationships):
        relationship = _component_relationship(indices, pair_relationships)
        members = [candidates[index] for index in indices]
        if relationship == "same_session":
            canonical, unresolved_fields, excluded = _canonicalize(
                members,
                preference,
            )
        else:
            canonical, unresolved_fields, excluded = {}, [], []
        clusters.append({
            "relationship": relationship,
            "member_workout_ids": [candidate.workout_id for candidate in members],
            "canonical_fields": canonical,
            "unresolved_fields": unresolved_fields,
            "excluded_workout_ids": excluded,
        })

    if any(cluster["relationship"] == "unresolved" for cluster in clusters):
        top_relationship: Relationship = "unresolved"
        relationship_reason = "one_or_more_relationships_unresolved"
    elif len(clusters) == 1 and clusters[0]["relationship"] == "same_session":
        top_relationship = "same_session"
        relationship_reason = "all_candidates_complete_same_session"
    else:
        top_relationship = "distinct"
        relationship_reason = "candidates_partition_into_distinct_clusters"

    return {
        "relationship": top_relationship,
        "relationship_reason": relationship_reason,
        "preference": preference,
        "classification_policy": dict(_POLICY),
        "members": [_public_member(candidate) for candidate in candidates],
        "pairwise_evidence": pairwise_evidence,
        "clusters": clusters,
        "source_errors": source_errors,
        "availability": {
            "state": "partial" if source_errors else "available",
            "reason": "candidate_source_unavailable" if source_errors else None,
            "source": CLASSIFIER_SOURCE,
        },
    }
