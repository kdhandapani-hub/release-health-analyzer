"""KPI summaries and layer health classification."""

from __future__ import annotations

import pandas as pd


def summarize(
    api: pd.DataFrame,
    kafka: pd.DataFrame,
    db: pd.DataFrame,
) -> dict[str, float | str | None]:
    summary: dict[str, float | str | None] = {
        "api_pass_rate": None,
        "api_p95_latency": None,
        "kafka_max_lag": None,
        "kafka_avg_error_rate": None,
        "db_avg_elapsed": None,
        "db_max_sql_elapsed": None,
        "db_top_wait_class": None,
        "db_active_sessions": None,
    }

    if not api.empty:
        summary["api_pass_rate"] = float(api["passed"].mean() * 100)
        summary["api_p95_latency"] = float(api["latency_ms"].quantile(0.95))

    if not kafka.empty:
        summary["kafka_max_lag"] = float(kafka["lag"].max())
        summary["kafka_avg_error_rate"] = float(kafka["error_rate"].mean())

    if not db.empty:
        summary["db_avg_elapsed"] = float(db["avg_elapsed_ms"].mean())
        summary["db_max_sql_elapsed"] = float(db["avg_elapsed_ms"].max())
        wait_time_by_class = db.groupby("top_wait_class")["avg_elapsed_ms"].sum()
        summary["db_top_wait_class"] = str(wait_time_by_class.idxmax())
        summary["db_active_sessions"] = float(db["active_sessions"].mean())
    return summary


def health_for_layer(layer: str, metrics: dict) -> str:
    """Return healthy, warning, critical, or unavailable for one layer."""
    if layer == "API":
        values = (metrics["api_pass_rate"], metrics["api_p95_latency"])
        if any(value is None for value in values):
            return "unavailable"
        passed, p95 = values
        if passed < 95 or p95 > 1500:
            return "critical"
        if passed < 98 or p95 > 700:
            return "warning"
        return "healthy"

    if layer == "Messaging":
        values = (metrics["kafka_max_lag"], metrics["kafka_avg_error_rate"])
        if any(value is None for value in values):
            return "unavailable"
        lag, error_rate = values
        if lag >= 5000 or error_rate >= 3:
            return "critical"
        if lag >= 500 or error_rate >= 0.5:
            return "warning"
        return "healthy"

    values = (
        metrics["db_avg_elapsed"],
        metrics["db_active_sessions"],
        metrics["db_max_sql_elapsed"],
    )
    if any(value is None for value in values):
        return "unavailable"
    elapsed, sessions, max_sql_elapsed = values
    if elapsed >= 500 or sessions >= 8 or max_sql_elapsed >= 500:
        return "critical"
    if elapsed >= 200 or sessions >= 4 or max_sql_elapsed >= 200:
        return "warning"
    return "healthy"
