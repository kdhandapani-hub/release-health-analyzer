"""Aggregations used by the API Test Results view."""

from __future__ import annotations

import pandas as pd

PASS_RATE_COLUMNS = ["group", "run_count", "pass_rate_pct"]
FAILURE_COLUMNS = ["failure_reason", "failed_runs", "failure_pct"]
RELEASE_COLUMNS = [
    "release_tag",
    "run_count",
    "pass_rate_pct",
    "pass_rate_delta_pp",
    "p95_latency_ms",
    "p95_delta_ms",
]
P95_TIME_COLUMNS = ["timestamp", "service", "p95_latency_ms"]


def _pass_rate_by(api: pd.DataFrame, dimension: str) -> pd.DataFrame:
    if api.empty:
        return pd.DataFrame(columns=PASS_RATE_COLUMNS)

    summary = (
        api.groupby(dimension, dropna=False)
        .agg(run_count=("passed", "size"), pass_rate=("passed", "mean"))
        .reset_index()
        .rename(columns={dimension: "group"})
    )
    summary["pass_rate_pct"] = summary.pop("pass_rate") * 100
    return summary[PASS_RATE_COLUMNS].sort_values(
        "pass_rate_pct", ascending=True, kind="stable"
    )


def pass_rate_by_service(api: pd.DataFrame) -> pd.DataFrame:
    """Return run counts and pass rates grouped by API service."""
    return _pass_rate_by(api, "service")


def pass_rate_by_endpoint(api: pd.DataFrame) -> pd.DataFrame:
    """Return run counts and pass rates grouped by endpoint."""
    return _pass_rate_by(api, "endpoint")


def latency_percentiles(api: pd.DataFrame) -> pd.DataFrame:
    """Return p50, p95, and p99 latency in milliseconds."""
    if api.empty:
        return pd.DataFrame(columns=["percentile", "latency_ms"])

    return pd.DataFrame(
        [
            {"percentile": f"p{int(quantile * 100)}", "latency_ms": api["latency_ms"].quantile(quantile)}
            for quantile in (0.50, 0.95, 0.99)
        ]
    )


def p95_latency_over_time_by_service(api: pd.DataFrame) -> pd.DataFrame:
    """Return hourly p95 latency in milliseconds, split by API service."""
    if api.empty:
        return pd.DataFrame(columns=P95_TIME_COLUMNS)

    samples = api[["timestamp", "service", "latency_ms"]].copy()
    samples["hour"] = pd.to_datetime(samples["timestamp"], utc=True).dt.floor("h")
    result = (
        samples.groupby(["hour", "service"], as_index=False, sort=True)
        .agg(p95_latency_ms=("latency_ms", lambda values: values.quantile(0.95)))
        .rename(columns={"hour": "timestamp"})
    )
    return result[P95_TIME_COLUMNS].sort_values(
        ["service", "timestamp"], kind="stable"
    )


def failure_reason_breakdown(api: pd.DataFrame) -> pd.DataFrame:
    """Return failed-run counts and shares by failure reason."""
    if api.empty:
        return pd.DataFrame(columns=FAILURE_COLUMNS)

    failures = api.loc[~api["passed"], "failure_reason"].fillna("").astype(str).str.strip()
    if failures.empty:
        return pd.DataFrame(columns=FAILURE_COLUMNS)

    failures = failures.replace("", "Unspecified")
    summary = failures.value_counts().rename_axis("failure_reason").reset_index(name="failed_runs")
    summary["failure_pct"] = summary["failed_runs"] / len(failures) * 100
    return summary[FAILURE_COLUMNS]


def release_comparison(api: pd.DataFrame) -> pd.DataFrame:
    """Compare pass rate and p95 latency by release in chronological order."""
    if api.empty:
        return pd.DataFrame(columns=RELEASE_COLUMNS)

    tagged = api.copy()
    tagged["release_tag"] = tagged["release_tag"].fillna("Unknown").astype(str)
    summary = (
        tagged.groupby("release_tag", dropna=False)
        .agg(
            first_seen=("timestamp", "min"),
            run_count=("passed", "size"),
            pass_rate_pct=("passed", lambda passed: passed.mean() * 100),
            p95_latency_ms=("latency_ms", lambda latency: latency.quantile(0.95)),
        )
        .sort_values(["first_seen", "release_tag"], kind="stable")
        .reset_index()
    )
    summary["pass_rate_delta_pp"] = summary["pass_rate_pct"].diff()
    summary["p95_delta_ms"] = summary["p95_latency_ms"].diff()
    return summary[RELEASE_COLUMNS]
