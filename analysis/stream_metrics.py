"""Aggregations for event-stream health charts and tables."""

from __future__ import annotations

import pandas as pd

from analysis.thresholds import classify_messaging_status


def lag_heatmap_matrix(kafka: pd.DataFrame) -> pd.DataFrame:
    """Return lag indexed by topic/partition and timestamp."""
    if kafka.empty:
        return pd.DataFrame()

    samples = kafka.copy()
    samples["topic_partition"] = samples.apply(
        lambda row: f'{row["topic"]} / p{int(row["partition"])}', axis=1
    )
    return (
        samples.pivot_table(
            index="topic_partition",
            columns="timestamp",
            values="lag",
            aggfunc="max",
        )
        .sort_index(axis=0)
        .sort_index(axis=1)
    )


def throughput_by_topic(kafka: pd.DataFrame) -> pd.DataFrame:
    """Sum partition throughput to topic-level messages per second."""
    if kafka.empty:
        return pd.DataFrame(columns=["timestamp", "topic", "msgs_per_sec"])
    return (
        kafka.groupby(["timestamp", "topic"], as_index=False)["msgs_per_sec"]
        .sum()
        .sort_values(["topic", "timestamp"], kind="stable")
    )


def error_rate_by_topic(kafka: pd.DataFrame) -> pd.DataFrame:
    """Calculate throughput-weighted topic error rates for each timestamp."""
    if kafka.empty:
        return pd.DataFrame(columns=["timestamp", "topic", "error_rate_pct"])

    samples = kafka.assign(
        weighted_errors=lambda frame: frame["error_rate"] * frame["msgs_per_sec"]
    )
    summary = (
        samples.groupby(["timestamp", "topic"], as_index=False)
        .agg(
            weighted_errors=("weighted_errors", "sum"),
            total_throughput=("msgs_per_sec", "sum"),
            mean_error_rate=("error_rate", "mean"),
        )
    )
    summary["error_rate_pct"] = (
        summary["weighted_errors"] / summary["total_throughput"]
    ).where(
        summary["total_throughput"] > 0,
        summary["mean_error_rate"],
    )
    return summary[["timestamp", "topic", "error_rate_pct"]].sort_values(
        ["topic", "timestamp"], kind="stable"
    )


def consumer_group_lag_summary(kafka: pd.DataFrame) -> pd.DataFrame:
    """Summarize lag, peak timestamp, and shared status per consumer group."""
    columns = ["consumer_group", "max_lag", "avg_lag", "peak_time", "status"]
    if kafka.empty:
        return pd.DataFrame(columns=columns)

    rows = []
    for consumer_group, group in kafka.groupby("consumer_group", sort=True):
        peak_index = group["lag"].idxmax()
        max_lag = float(group.loc[peak_index, "lag"])
        rows.append(
            {
                "consumer_group": consumer_group,
                "max_lag": max_lag,
                "avg_lag": float(group["lag"].mean()),
                "peak_time": group.loc[peak_index, "timestamp"],
                "status": classify_messaging_status(max_lag, None),
            }
        )
    return pd.DataFrame(rows, columns=columns).sort_values(
        "max_lag", ascending=False, kind="stable"
    )
