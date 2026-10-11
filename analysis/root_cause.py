"""Deterministic, threshold-based cross-layer root-cause correlation."""

from __future__ import annotations

import pandas as pd

from analysis.infrastructure import (
    classify_infrastructure_episodes,
    infrastructure_hourly_metrics,
)
from analysis.thresholds import (
    API_FAILURE_RATE_CRITICAL_PCT,
    API_FAILURE_RATE_WARNING_PCT,
    API_P95_CRITICAL_MS,
    API_P95_WARNING_MS,
    DB_ELAPSED_CRITICAL_MS,
    DB_ELAPSED_WARNING_MS,
    KAFKA_LAG_CRITICAL_MESSAGES,
    KAFKA_LAG_WARNING_MESSAGES,
)

ROOT_CAUSE_LAYERS = ("Database", "API", "Messaging")
CLEARANCE_WINDOW = pd.Timedelta(hours=3)


def _classify(status_frame, warning_mask, critical_mask):
    frame = status_frame.copy()
    frame["status"] = "healthy"
    frame.loc[warning_mask, "status"] = "warning"
    frame.loc[critical_mask, "status"] = "critical"
    return frame


def database_hourly_metrics(db: pd.DataFrame) -> pd.DataFrame:
    """Build execution-weighted DB averages and hourly slowest SQL values."""
    columns = [
        "timestamp",
        "avg_elapsed_ms",
        "slowest_sql_elapsed_ms",
        "slowest_sql_id",
        "status",
    ]
    if db.empty:
        return pd.DataFrame(columns=columns)

    samples = db.copy()
    samples["executions"] = pd.to_numeric(samples["executions"], errors="coerce")
    samples["avg_elapsed_ms"] = pd.to_numeric(
        samples["avg_elapsed_ms"], errors="coerce"
    )
    samples["db_time_ms"] = samples["executions"] * samples["avg_elapsed_ms"]
    hourly = (
        samples.groupby("timestamp", as_index=False, sort=True)
        .agg(
            total_db_time_ms=("db_time_ms", "sum"),
            total_executions=("executions", "sum"),
            slowest_sql_elapsed_ms=("avg_elapsed_ms", "max"),
        )
        .sort_values("timestamp", kind="stable")
    )
    hourly["avg_elapsed_ms"] = (
        hourly["total_db_time_ms"] / hourly["total_executions"].replace(0, pd.NA)
    ).fillna(0.0)
    slowest_sql = (
        samples.sort_values(
            ["timestamp", "avg_elapsed_ms", "sql_id"],
            ascending=[True, True, True],
            kind="stable",
        )
        .groupby("timestamp", sort=False)
        .tail(1)[["timestamp", "sql_id"]]
    )
    hourly = hourly.merge(slowest_sql, on="timestamp", how="left")
    hourly = hourly.rename(columns={"sql_id": "slowest_sql_id"})
    warning = (
        (hourly["avg_elapsed_ms"] >= DB_ELAPSED_WARNING_MS)
        | (hourly["slowest_sql_elapsed_ms"] >= DB_ELAPSED_WARNING_MS)
    )
    critical = (
        (hourly["avg_elapsed_ms"] >= DB_ELAPSED_CRITICAL_MS)
        | (hourly["slowest_sql_elapsed_ms"] >= DB_ELAPSED_CRITICAL_MS)
    )
    hourly = _classify(hourly, warning, critical)
    return hourly[columns]


def api_hourly_metrics(api: pd.DataFrame) -> pd.DataFrame:
    """Aggregate API failures and p95 latency into UTC hour buckets."""
    columns = ["timestamp", "failure_rate_pct", "p95_latency_ms", "status"]
    if api.empty:
        return pd.DataFrame(columns=columns)

    samples = api.copy()
    samples["timestamp"] = pd.to_datetime(samples["timestamp"], utc=True)
    if samples["passed"].dtype == object:
        samples["passed"] = (
            samples["passed"].astype(str).str.lower().eq("true")
        )
    else:
        samples["passed"] = samples["passed"].astype(bool)
    samples["hour"] = samples["timestamp"].dt.floor("h")
    hourly = (
        samples.groupby("hour", as_index=False, sort=True)
        .agg(
            failure_rate_pct=(
                "passed",
                lambda passed: (~passed).mean() * 100,
            ),
            p95_latency_ms=("latency_ms", lambda values: values.quantile(0.95)),
        )
        .rename(columns={"hour": "timestamp"})
    )
    warning = (
        (hourly["failure_rate_pct"] >= API_FAILURE_RATE_WARNING_PCT)
        | (hourly["p95_latency_ms"] >= API_P95_WARNING_MS)
    )
    critical = (
        (hourly["failure_rate_pct"] >= API_FAILURE_RATE_CRITICAL_PCT)
        | (hourly["p95_latency_ms"] >= API_P95_CRITICAL_MS)
    )
    hourly = _classify(hourly, warning, critical)
    return hourly[columns]


def messaging_hourly_metrics(kafka: pd.DataFrame) -> pd.DataFrame:
    """Use the maximum filtered consumer lag in each UTC hour."""
    columns = ["timestamp", "max_lag", "status"]
    if kafka.empty:
        return pd.DataFrame(columns=columns)

    hourly = (
        kafka.groupby("timestamp", as_index=False, sort=True)["lag"]
        .max()
        .rename(columns={"lag": "max_lag"})
    )
    warning = hourly["max_lag"] >= KAFKA_LAG_WARNING_MESSAGES
    critical = hourly["max_lag"] >= KAFKA_LAG_CRITICAL_MESSAGES
    hourly = _classify(hourly, warning, critical)
    return hourly[columns]


def analyze_root_cause(
    api: pd.DataFrame,
    kafka: pd.DataFrame,
    db: pd.DataFrame,
    changes: pd.DataFrame,
    start_day,
    end_day,
    selected_event_ids: list[str] | None = None,
    infra: pd.DataFrame | None = None,
) -> dict:
    """Return filtered hourly lanes, first breaches, likely trigger, and event status."""
    lanes = {
        "Database": database_hourly_metrics(db),
        "API": api_hourly_metrics(api),
        "Messaging": messaging_hourly_metrics(kafka),
    }
    if infra is not None:
        lanes["Infrastructure"] = infrastructure_hourly_metrics(infra)
    sequence = []
    first_breaches = []
    critical_breaches = []
    for layer in ROOT_CAUSE_LAYERS:
        lane = lanes[layer].sort_values("timestamp", kind="stable").reset_index(drop=True)
        warning_rows = lane.loc[lane["status"].isin(["warning", "critical"])]
        critical_rows = lane.loc[lane["status"] == "critical"]
        if not warning_rows.empty:
            critical_timestamp = (
                critical_rows["timestamp"].min()
                if not critical_rows.empty
                else None
            )
            onset_timestamp = warning_rows["timestamp"].min()
            if critical_timestamp is not None:
                critical_index = lane.index[lane["timestamp"] == critical_timestamp][0]
                onset_timestamp = critical_timestamp
                previous_timestamp = critical_timestamp
                for sample in reversed(
                    list(lane.iloc[:critical_index].itertuples(index=False))
                ):
                    if (
                        sample.status not in ("warning", "critical")
                        or previous_timestamp - sample.timestamp
                        != pd.Timedelta(hours=1)
                    ):
                        break
                    onset_timestamp = sample.timestamp
                    previous_timestamp = sample.timestamp
            sequence.append(
                {
                    "layer": layer,
                    "onset_timestamp": onset_timestamp,
                    "critical_timestamp": critical_timestamp,
                }
            )
        critical_breaches.extend(
            {"layer": layer, "timestamp": timestamp}
            for timestamp in critical_rows["timestamp"]
        )
        if not critical_rows.empty:
            first_breaches.append(
                {
                    "layer": layer,
                    "timestamp": critical_rows["timestamp"].min(),
                }
            )
    layer_order = {layer: index for index, layer in enumerate(ROOT_CAUSE_LAYERS)}
    first_breaches.sort(
        key=lambda breach: (breach["timestamp"], layer_order[breach["layer"]])
    )
    critical_breaches.sort(
        key=lambda breach: (breach["timestamp"], layer_order[breach["layer"]])
    )
    sequence.sort(
        key=lambda breach: (
            breach["onset_timestamp"],
            layer_order[breach["layer"]],
        )
    )
    first_warning = (
        {
            "layer": sequence[0]["layer"],
            "timestamp": sequence[0]["onset_timestamp"],
        }
        if sequence
        else None
    )
    first_breach = first_breaches[0] if first_breaches else None

    start = pd.Timestamp(start_day).tz_localize("UTC")
    end = (pd.Timestamp(end_day) + pd.Timedelta(days=1)).tz_localize("UTC")
    event_frame = changes.copy()
    if event_frame.empty:
        event_frame = pd.DataFrame(
            columns=["timestamp", "change_id", "change_type", "description"]
        )
    else:
        event_frame["timestamp"] = pd.to_datetime(
            event_frame["timestamp"], utc=True
        )
        event_frame = event_frame.loc[
            (event_frame["timestamp"] >= start) & (event_frame["timestamp"] < end)
        ]
        if selected_event_ids:
            event_frame = event_frame.loc[
                event_frame["change_id"].isin(selected_event_ids)
            ]
        event_frame = event_frame.sort_values(
            ["timestamp", "change_id"], kind="stable"
        )

    trigger = None
    if first_breach is not None and not event_frame.empty:
        prior_changes = event_frame.loc[
            event_frame["timestamp"] < first_breach["timestamp"]
        ]
        if not prior_changes.empty:
            trigger = prior_changes.iloc[-1].to_dict()

    trigger_id = trigger["change_id"] if trigger else None
    event_assessments = []
    for event in event_frame.to_dict("records"):
        if event["change_id"] == trigger_id:
            continue
        event_time = event["timestamp"]
        window_end = event_time + CLEARANCE_WINDOW
        nearby_breaches = [
            breach
            for breach in critical_breaches
            if event_time < breach["timestamp"] <= window_end
        ]
        if nearby_breaches:
            first_nearby = nearby_breaches[0]
            event_assessments.append(
                {
                    **event,
                    "status": "inconclusive",
                    "reason": (
                        f"Critical {first_nearby['layer']} breach at "
                        f"{first_nearby['timestamp']} within 3 hours."
                    ),
                }
            )
        else:
            event_assessments.append(
                {
                    **event,
                    "status": "cleared",
                    "reason": "No critical breach in any layer for 3 hours after the change.",
                }
            )

    infrastructure_assessments = (
        classify_infrastructure_episodes(infra, critical_breaches)
        if infra is not None
        else []
    )

    return {
        "lanes": lanes,
        "first_breaches": first_breaches,
        "critical_breaches": critical_breaches,
        "first_warning": first_warning,
        "first_breach": first_breach,
        "trigger": trigger,
        "sequence": sequence,
        "event_assessments": event_assessments,
        "infrastructure_assessments": infrastructure_assessments,
        "changes": event_frame,
    }
