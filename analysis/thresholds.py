"""Shared layer thresholds, health classification, and status colors."""

from __future__ import annotations

API_PASS_RATE_SLA_PCT = 98.0
API_PASS_RATE_RED_BELOW_PCT = 95.0
API_FAILURE_RATE_WARNING_PCT = 100.0 - API_PASS_RATE_SLA_PCT
API_FAILURE_RATE_CRITICAL_PCT = 100.0 - API_PASS_RATE_RED_BELOW_PCT
API_P95_WARNING_MS = 500.0
API_P95_CRITICAL_MS = 1000.0

KAFKA_LAG_WARNING_MESSAGES = 500
KAFKA_LAG_CRITICAL_MESSAGES = 5000
KAFKA_ERROR_RATE_WARNING_PCT = 0.5
KAFKA_ERROR_RATE_CRITICAL_PCT = 3.0

DB_ELAPSED_WARNING_MS = 200.0
DB_ELAPSED_CRITICAL_MS = 500.0
DB_ACTIVE_SESSIONS_WARNING = 4.0
DB_ACTIVE_SESSIONS_CRITICAL = 8.0

INFRA_CPU_WARNING_PCT = 75.0
INFRA_CPU_CRITICAL_PCT = 90.0
INFRA_MEMORY_WARNING_PCT = 80.0
INFRA_MEMORY_CRITICAL_PCT = 90.0
INFRA_IO_WAIT_WARNING_PCT = 20.0
INFRA_IO_WAIT_CRITICAL_PCT = 40.0

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


def classify_database_elapsed(elapsed_ms: float | None) -> str:
    """Classify a SQL elapsed-time observation using shared DB thresholds."""
    if elapsed_ms is None:
        return "unavailable"
    if elapsed_ms >= DB_ELAPSED_CRITICAL_MS:
        return "critical"
    if elapsed_ms >= DB_ELAPSED_WARNING_MS:
        return "warning"
    return "healthy"


def classify_database_status(
    avg_elapsed_ms: float | None,
    active_sessions: float | None,
    max_sql_elapsed_ms: float | None,
) -> str:
    """Classify overall DB health from elapsed time and active sessions."""
    if any(
        value is None
        for value in (avg_elapsed_ms, active_sessions, max_sql_elapsed_ms)
    ):
        return "unavailable"
    if (
        avg_elapsed_ms >= DB_ELAPSED_CRITICAL_MS
        or active_sessions >= DB_ACTIVE_SESSIONS_CRITICAL
        or max_sql_elapsed_ms >= DB_ELAPSED_CRITICAL_MS
    ):
        return "critical"
    if (
        avg_elapsed_ms >= DB_ELAPSED_WARNING_MS
        or active_sessions >= DB_ACTIVE_SESSIONS_WARNING
        or max_sql_elapsed_ms >= DB_ELAPSED_WARNING_MS
    ):
        return "warning"
    return "healthy"


def classify_infrastructure_status(
    cpu_pct: float | None,
    memory_pct: float | None,
    io_wait_pct: float | None,
    restarts: float | None = 0,
    oom_kills: float | None = 0,
    status: str | None = None,
) -> str:
    """Classify a host or pod using resource limits and process health."""
    status_value = str(status or "").strip().lower()
    if status_value in {"notready", "crashloopbackoff", "down"}:
        return "critical"

    numeric_values = (cpu_pct, memory_pct, io_wait_pct)
    if all(value is None for value in numeric_values) and status_value == "":
        return "unavailable"

    if (
        (restarts is not None and restarts > 0)
        or (oom_kills is not None and oom_kills > 0)
        or (cpu_pct is not None and cpu_pct >= INFRA_CPU_CRITICAL_PCT)
        or (memory_pct is not None and memory_pct >= INFRA_MEMORY_CRITICAL_PCT)
        or (io_wait_pct is not None and io_wait_pct >= INFRA_IO_WAIT_CRITICAL_PCT)
    ):
        return "critical"

    if (
        status_value == "degraded"
        or (cpu_pct is not None and cpu_pct >= INFRA_CPU_WARNING_PCT)
        or (memory_pct is not None and memory_pct >= INFRA_MEMORY_WARNING_PCT)
        or (io_wait_pct is not None and io_wait_pct >= INFRA_IO_WAIT_WARNING_PCT)
    ):
        return "warning"
    return "healthy"
