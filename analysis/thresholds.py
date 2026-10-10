"""Shared layer thresholds, health classification, and status colors."""

from __future__ import annotations

API_PASS_RATE_SLA_PCT = 98.0
API_PASS_RATE_RED_BELOW_PCT = 95.0

KAFKA_LAG_WARNING_MESSAGES = 500
KAFKA_LAG_CRITICAL_MESSAGES = 5000
KAFKA_ERROR_RATE_WARNING_PCT = 0.5
KAFKA_ERROR_RATE_CRITICAL_PCT = 3.0

STATUS_COLORS = {
    "healthy": "#22c55e",
    "warning": "#f59e0b",
    "critical": "#ef4444",
    "unavailable": "#94a3b8",
}


def classify_api_pass_rate(pass_rate_pct: float | None) -> str:
    """Classify an API pass rate using the shared SLA and status cutoffs."""
    if pass_rate_pct is None:
        return "unavailable"
    if pass_rate_pct >= API_PASS_RATE_SLA_PCT:
        return "healthy"
    if pass_rate_pct >= API_PASS_RATE_RED_BELOW_PCT:
        return "warning"
    return "critical"


def classify_messaging_status(
    max_lag: float | None,
    error_rate_pct: float | None,
) -> str:
    """Classify messaging health from any available lag and error-rate metrics."""
    if max_lag is None and error_rate_pct is None:
        return "unavailable"
    if (
        max_lag is not None
        and max_lag >= KAFKA_LAG_CRITICAL_MESSAGES
    ) or (
        error_rate_pct is not None
        and error_rate_pct >= KAFKA_ERROR_RATE_CRITICAL_PCT
    ):
        return "critical"
    if (
        max_lag is not None
        and max_lag >= KAFKA_LAG_WARNING_MESSAGES
    ) or (
        error_rate_pct is not None
        and error_rate_pct >= KAFKA_ERROR_RATE_WARNING_PCT
    ):
        return "warning"
    return "healthy"
