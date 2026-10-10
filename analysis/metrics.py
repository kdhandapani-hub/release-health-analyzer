"""KPI summaries and layer health classification."""

from __future__ import annotations

import pandas as pd

from analysis.thresholds import (
    classify_api_pass_rate,
    classify_database_status,
    classify_messaging_status,
)


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
        "db_slowest_sql_id": None,
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
        slowest_row = db.loc[db["avg_elapsed_ms"].idxmax()]
        summary["db_slowest_sql_id"] = str(slowest_row["sql_id"])
        wait_time_by_class = db.groupby("top_wait_class")["avg_elapsed_ms"].sum()
        summary["db_top_wait_class"] = str(wait_time_by_class.idxmax())
        summary["db_active_sessions"] = float(db["active_sessions"].mean())
    return summary


def health_for_layer(layer: str, metrics: dict) -> str:
    """Return healthy, warning, critical, or unavailable for one layer."""
    if layer == "API":
        return classify_api_pass_rate(metrics["api_pass_rate"])

    if layer == "Messaging":
        return classify_messaging_status(
            metrics["kafka_max_lag"],
            metrics["kafka_avg_error_rate"],
        )

    return classify_database_status(
        metrics["db_avg_elapsed"],
        metrics["db_active_sessions"],
        metrics["db_max_sql_elapsed"],
    )
