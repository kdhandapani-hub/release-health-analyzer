"""Aggregations and plan-regression analysis for database health."""

from __future__ import annotations

import pandas as pd

from analysis.thresholds import classify_database_elapsed


SQL_SUMMARY_COLUMNS = [
    "sql_id",
    "db_users",
    "sql_type",
    "executions",
    "avg_elapsed_ms",
    "max_elapsed_ms",
    "top_wait_class",
    "db_time_sec",
    "status",
]
PLAN_REGRESSION_COLUMNS = [
    "sql_id",
    "old_plan",
    "new_plan",
    "change_time",
    "elapsed_before_ms",
    "elapsed_after_ms",
    "regression_factor",
]


def _prepare_db(db: pd.DataFrame) -> pd.DataFrame:
    """Copy DB data and derive connection-user dimensions and total DB time."""
    if db.empty:
        return db.copy()
    prepared = db.copy()
    identity = prepared["db_user"].astype(str).str.extract(
        r"^SVC_(.+)_(API|CONSUMER)$"
    )
    prepared["service"] = identity[0].str.lower().fillna(prepared["db_user"])
    prepared["caller_type"] = identity[1].map(
        {"API": "API", "CONSUMER": "Consumer"}
    ).fillna("Unknown")
    prepared["db_time_ms"] = (
        prepared["executions"].astype(float)
        * prepared["avg_elapsed_ms"].astype(float)
    )
    return prepared


def db_time_by_connection_user(db: pd.DataFrame) -> pd.DataFrame:
    """Total SQL elapsed time in seconds by service account and caller path."""
    columns = ["service", "caller_type", "db_user", "db_time_sec"]
    if db.empty:
        return pd.DataFrame(columns=columns)
    prepared = _prepare_db(db)
    summary = (
        prepared.groupby(
            ["service", "caller_type", "db_user"], as_index=False, sort=True
        )["db_time_ms"]
        .sum()
    )
    summary["db_time_sec"] = summary.pop("db_time_ms") / 1000
    return summary[columns].sort_values(
        ["service", "caller_type"], kind="stable"
    )


def top_sql_summary(db: pd.DataFrame) -> pd.DataFrame:
    """Summarize SQL activity, ranking statements by total elapsed DB time."""
    if db.empty:
        return pd.DataFrame(columns=SQL_SUMMARY_COLUMNS)
    prepared = _prepare_db(db)
    rows = []
    for sql_id, group in prepared.groupby("sql_id", sort=True):
        executions = float(group["executions"].sum())
        avg_elapsed = (
            float(group["db_time_ms"].sum() / executions)
            if executions > 0
            else 0.0
        )
        wait_class_time = group.groupby("top_wait_class")["db_time_ms"].sum()
        rows.append(
            {
                "sql_id": str(sql_id),
                "db_users": ", ".join(sorted(group["db_user"].astype(str).unique())),
                "sql_type": ", ".join(sorted(group["sql_type"].astype(str).unique())),
                "executions": int(executions),
                "avg_elapsed_ms": avg_elapsed,
                # The source is hourly aggregate data, so this is the highest
                # sampled hourly average, not a per-execution maximum.
                "max_elapsed_ms": float(group["avg_elapsed_ms"].max()),
                "top_wait_class": str(wait_class_time.idxmax()),
                "db_time_sec": float(group["db_time_ms"].sum() / 1000),
                "status": classify_database_elapsed(
                    float(group["avg_elapsed_ms"].max())
                ),
            }
        )
    return pd.DataFrame(rows, columns=SQL_SUMMARY_COLUMNS).sort_values(
        ["db_time_sec", "sql_id"], ascending=[False, True], kind="stable"
    )


def sql_elapsed_trend(db: pd.DataFrame) -> pd.DataFrame:
    """Return execution-weighted average elapsed time by SQL ID and hour."""
    columns = ["timestamp", "sql_id", "avg_elapsed_ms", "db_time_ms"]
    if db.empty:
        return pd.DataFrame(columns=columns)
    prepared = _prepare_db(db)
    trend = (
        prepared.groupby(["timestamp", "sql_id"], as_index=False, sort=True)
        .agg(
            executions=("executions", "sum"),
            db_time_ms=("db_time_ms", "sum"),
        )
    )
    trend["avg_elapsed_ms"] = (
        trend["db_time_ms"] / trend["executions"].replace(0, pd.NA)
    ).fillna(0.0)
    return trend[columns].sort_values(
        ["sql_id", "timestamp"], kind="stable"
    )


def wait_class_percent_over_time(db: pd.DataFrame) -> pd.DataFrame:
    """Estimate each wait class's percentage of total DB time per hour.

    Hourly rows only include their top wait class and a wait-time percentage.
    The estimated wait-class share is weighted by executions and elapsed time;
    remaining time is attributed to CPU so the stacked area totals 100%.
    """
    columns = ["timestamp", "wait_class", "db_time_pct"]
    if db.empty:
        return pd.DataFrame(columns=columns)
    prepared = _prepare_db(db)
    is_cpu = prepared["top_wait_class"].eq("CPU")
    prepared["wait_class_time_ms"] = prepared["db_time_ms"].where(
        is_cpu,
        prepared["db_time_ms"] * prepared["wait_time_pct"].astype(float) / 100,
    )
    prepared["cpu_time_ms"] = prepared["db_time_ms"] - prepared[
        "wait_class_time_ms"
    ].where(~is_cpu, 0)
    prepared.loc[is_cpu, "cpu_time_ms"] = prepared.loc[is_cpu, "db_time_ms"]

    wait_samples = prepared.loc[~is_cpu, ["timestamp", "top_wait_class", "wait_class_time_ms"]]
    wait_samples = wait_samples.rename(columns={"top_wait_class": "wait_class"})
    cpu_samples = prepared[["timestamp", "cpu_time_ms"]].rename(
        columns={"cpu_time_ms": "wait_class_time_ms"}
    )
    cpu_samples["wait_class"] = "CPU"
    contributions = pd.concat([wait_samples, cpu_samples], ignore_index=True)
    totals = prepared.groupby("timestamp")["db_time_ms"].sum()
    summary = (
        contributions.groupby(["timestamp", "wait_class"], as_index=False)[
            "wait_class_time_ms"
        ]
        .sum()
    )
    summary["db_time_pct"] = (
        summary["wait_class_time_ms"]
        / summary["timestamp"].map(totals)
        * 100
    )

    timestamps = sorted(prepared["timestamp"].unique())
    wait_classes = sorted(summary["wait_class"].unique())
    full_index = pd.MultiIndex.from_product(
        [timestamps, wait_classes], names=["timestamp", "wait_class"]
    )
    return (
        summary.set_index(["timestamp", "wait_class"])["db_time_pct"]
        .reindex(full_index, fill_value=0.0)
        .rename("db_time_pct")
        .reset_index()
        .sort_values(["wait_class", "timestamp"], kind="stable")
    )[columns]


def detect_plan_regressions(
    db: pd.DataFrame,
    start_day=None,
    end_day=None,
) -> pd.DataFrame:
    """Find plan-hash transitions where the next hourly average elapsed regresses."""
    if db.empty:
        return pd.DataFrame(columns=PLAN_REGRESSION_COLUMNS)
    prepared = _prepare_db(db)
    snapshots = (
        prepared.groupby(
            ["sql_id", "timestamp", "plan_hash_value"], as_index=False, sort=True
        )
        .agg(
            executions=("executions", "sum"),
            db_time_ms=("db_time_ms", "sum"),
        )
    )
    snapshots["avg_elapsed_ms"] = (
        snapshots["db_time_ms"] / snapshots["executions"].replace(0, pd.NA)
    ).fillna(0.0)
    # If more than one plan appears in an hour, compare the dominant plan by
    # execution count, which avoids creating a false transition within the hour.
    snapshots = snapshots.sort_values(
        ["sql_id", "timestamp", "executions", "plan_hash_value"],
        ascending=[True, True, False, True],
        kind="stable",
    ).drop_duplicates(["sql_id", "timestamp"], keep="first")

    start_bound = (
        pd.Timestamp(start_day).tz_localize("UTC")
        if start_day is not None
        else None
    )
    end_bound = (
        (pd.Timestamp(end_day) + pd.Timedelta(days=1)).tz_localize("UTC")
        if end_day is not None
        else None
    )

    regressions = []
    for sql_id, group in snapshots.groupby("sql_id", sort=True):
        ordered = group.sort_values("timestamp", kind="stable").reset_index(drop=True)
        for previous, current in zip(
            ordered.iloc[:-1].itertuples(index=False),
            ordered.iloc[1:].itertuples(index=False),
        ):
            if previous.plan_hash_value == current.plan_hash_value:
                continue
            if start_bound is not None and current.timestamp < start_bound:
                continue
            if end_bound is not None and current.timestamp >= end_bound:
                continue
            if current.avg_elapsed_ms <= previous.avg_elapsed_ms:
                continue
            factor = (
                float(current.avg_elapsed_ms / previous.avg_elapsed_ms)
                if previous.avg_elapsed_ms > 0
                else float("inf")
            )
            regressions.append(
                {
                    "sql_id": str(sql_id),
                    "old_plan": str(previous.plan_hash_value),
                    "new_plan": str(current.plan_hash_value),
                    "change_time": current.timestamp,
                    "elapsed_before_ms": float(previous.avg_elapsed_ms),
                    "elapsed_after_ms": float(current.avg_elapsed_ms),
                    "regression_factor": factor,
                }
            )
    return pd.DataFrame(regressions, columns=PLAN_REGRESSION_COLUMNS).sort_values(
        ["change_time", "sql_id"], kind="stable"
    )
