"""Validate Phase 4 windows and produce simulation-only, deterministic guidance."""

from typing import Mapping

from traffic_contracts.result import validate_result

REASONS = {
    "high": ("extend_green", 10, "high_congestion",
             "High congestion: suggest 10 additional green seconds in this simulation."),
    "medium": ("no_adjustment", 0, "medium_congestion",
               "Medium congestion: no signal adjustment suggested in this simulation."),
    "low": ("no_adjustment", 0, "low_congestion",
            "Low congestion: no signal adjustment suggested in this simulation."),
    "unknown": ("no_adjustment", 0, "insufficient_measurements",
                "Speed and occupancy are unavailable; no signal adjustment suggested."),
}


def recommend(result: Mapping[str, object]) -> dict:
    """Produce the approved v1 action with no clock, network or storage access."""
    source = validate_result(result)
    action, seconds, reason_code, rationale = REASONS[source["congestion"]]
    return {
        "schema_version": "1.0",
        "recommendation_id": source["window_id"] + "/recommendation/v1",
        "window_id": source["window_id"],
        "intersection_id": source["intersection_id"],
        "window_start": source["window_start"],
        "window_end": source["window_end"],
        "source_result": source,
        "action": action,
        "green_extension_seconds": seconds,
        "reason_code": reason_code,
        "rationale": rationale,
        "simulated": True,
    }
