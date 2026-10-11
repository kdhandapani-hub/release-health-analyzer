"""Infrastructure classification, summaries, and incident grouping."""

from __future__ import annotations

import pandas as pd

from analysis.thresholds import (
    INFRA_CPU_WARNING_PCT,
    INFRA_IO_WAIT_WARNING_PCT,
    INFRA_MEMORY_WARNING_PCT,
    classify_infrastructure_status,
)

INFRA_ASSET_COLUMNS = ["tier", "component", "node", "pod"]
STATUS_RANK = {"healthy": 0, "warning": 1, "critical": 2, "unavailable": -1}
RAW_STATUS_RANK = {
    "Up": 0,
    "Ready": 0,
    "Degraded": 1,
    "NotReady": 2,
    "CrashLoopBackOff": 2,
    "Down": 2,
}
HOURLY_COLUMNS = [
    "timestamp",
    "cpu_pct",
    "memory_pct",
    "io_wait_pct",
    "restarts",
    "oom_kills",
    "status",
]


def classify_infrastructure_frame(infra: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with shared-threshold health status on every sample."""
    samples = infra.copy()
    if samples.empty:
        samples["infra_status"] = pd.Series(dtype="object")
        return samples

    samples["infra_status"] = samples.apply(
        lambda row: classify_infrastructure_status(
            row.get("cpu_pct"),
            row.get("memory_pct"),
            row.get("io_wait_pct"),
            row.get("restarts", 0),
            row.get("oom_kills", 0),
            row.get("status"),
        ),
        axis=1,
    )
    return samples


def infrastructure_hourly_metrics(infra: pd.DataFrame) -> pd.DataFrame:
    """Aggregate the worst resource levels and component status by hour."""
    if infra.empty:
        return pd.DataFrame(columns=HOURLY_COLUMNS)

    samples = classify_infrastructure_frame(infra)
    samples["_raw_status_rank"] = (
        samples["status"].map(RAW_STATUS_RANK).fillna(0).astype(int)
    )
    hourly = (
        samples.groupby("timestamp", as_index=False, sort=True)
        .agg(
            cpu_pct=("cpu_pct", "max"),
            memory_pct=("memory_pct", "max"),
            io_wait_pct=("io_wait_pct", "max"),
            restarts=("restarts", "sum"),
            oom_kills=("oom_kills", "sum"),
            raw_status_rank=("_raw_status_rank", "max"),
        )
        .sort_values("timestamp", kind="stable")
    )
    raw_status_by_rank = {
        rank: status for status, rank in RAW_STATUS_RANK.items()
    }
    hourly["raw_status"] = hourly["raw_status_rank"].map(raw_status_by_rank)
    hourly["status"] = hourly.apply(
        lambda row: classify_infrastructure_status(
            row["cpu_pct"],
            row["memory_pct"],
            row["io_wait_pct"],
            row["restarts"],
            row["oom_kills"],
            row["raw_status"],
        ),
        axis=1,
    )
    return hourly[HOURLY_COLUMNS]


def _peak_metric(row) -> str:
    if row["oom_kills"] > 0 or row["restarts"] > 0:
        return (
            f"Restart {int(row['restarts'])}, "
            f"OOM {int(row['oom_kills'])}"
        )
    candidates = (
        ("CPU", row["cpu_pct"], INFRA_CPU_WARNING_PCT),
        ("Memory", row["memory_pct"], INFRA_MEMORY_WARNING_PCT),
        ("I/O wait", row["io_wait_pct"], INFRA_IO_WAIT_WARNING_PCT),
    )
    name, value, _ = max(
        candidates,
        key=lambda candidate: (
            candidate[1] / candidate[2] if candidate[1] is not None else -1
        ),
    )
    return f"{name} {value:.1f}%"


def unhealthy_infrastructure_table(infra: pd.DataFrame) -> pd.DataFrame:
    """Return one worst observed unhealthy sample per pod or host."""
    columns = ["component", "node", "pod", "peak_metric", "time", "status"]
    if infra.empty:
        return pd.DataFrame(columns=columns)

    samples = classify_infrastructure_frame(infra)
    samples = samples.loc[samples["infra_status"].isin(["warning", "critical"])].copy()
    if samples.empty:
        return pd.DataFrame(columns=columns)

    samples["_severity"] = samples["infra_status"].map(STATUS_RANK)
    samples["_event"] = samples["restarts"].fillna(0) + samples["oom_kills"].fillna(0)
    samples["_pressure"] = samples.apply(
        lambda row: max(
            row["cpu_pct"] / INFRA_CPU_WARNING_PCT,
            row["memory_pct"] / INFRA_MEMORY_WARNING_PCT,
            row["io_wait_pct"] / INFRA_IO_WAIT_WARNING_PCT,
        ),
        axis=1,
    )
    assets = []
    for _, group in samples.groupby(INFRA_ASSET_COLUMNS, dropna=False, sort=True):
        worst = group.sort_values(
            ["_severity", "_event", "_pressure", "timestamp"],
            ascending=[False, False, False, False],
            kind="stable",
        ).iloc[0]
        assets.append(
            {
                "component": worst["component"],
                "node": worst["node"],
                "pod": worst["pod"],
                "peak_metric": _peak_metric(worst),
                "time": pd.Timestamp(worst["timestamp"]).strftime(
                    "%Y-%m-%d %H:%M UTC"
                ),
                "status": worst["infra_status"].title(),
            }
        )
    return pd.DataFrame(assets, columns=columns).sort_values(
        ["status", "component", "node"],
        ascending=[True, True, True],
        kind="stable",
    )


def summarize_infrastructure(infra: pd.DataFrame) -> dict:
    """Build KPI values and layer health from the filtered infra samples."""
    if infra.empty:
        return {
            "peak_cpu_pct": None,
            "peak_memory_pct": None,
            "total_restarts": None,
            "unhealthy_assets": None,
            "health": "unavailable",
        }

    samples = classify_infrastructure_frame(infra)
    statuses = set(samples["infra_status"])
    health = (
        "critical"
        if "critical" in statuses
        else "warning"
        if "warning" in statuses
        else "healthy"
    )
    return {
        "peak_cpu_pct": float(samples["cpu_pct"].max()),
        "peak_memory_pct": float(samples["memory_pct"].max()),
        "total_restarts": int(samples["restarts"].sum()),
        "unhealthy_assets": len(unhealthy_infrastructure_table(samples)),
        "health": health,
    }


def infrastructure_event_episodes(infra: pd.DataFrame) -> list[dict]:
    """Group adjacent unhealthy samples into component-level infra episodes."""
    if infra.empty:
        return []
    samples = classify_infrastructure_frame(infra)
    samples = samples.loc[
        samples["infra_status"].isin(["warning", "critical"])
    ].sort_values([*INFRA_ASSET_COLUMNS, "timestamp"], kind="stable")
    episodes = []

    for identity, group in samples.groupby(INFRA_ASSET_COLUMNS, dropna=False, sort=True):
        rows = list(group.to_dict("records"))
        active = []
        for row in rows:
            timestamp = pd.Timestamp(row["timestamp"])
            if active and timestamp - pd.Timestamp(active[-1]["timestamp"]) > pd.Timedelta(hours=1):
                episodes.append(_episode_from_rows(identity, active))
                active = []
            active.append(row)
        if active:
            episodes.append(_episode_from_rows(identity, active))
    return episodes


def _episode_from_rows(identity, rows) -> dict:
    worst = max(rows, key=lambda row: STATUS_RANK[row["infra_status"]])
    tier, component, node, pod = identity
    return {
        "tier": tier,
        "component": component,
        "node": node,
        "pod": pod,
        "onset_timestamp": pd.Timestamp(rows[0]["timestamp"]),
        "end_timestamp": pd.Timestamp(rows[-1]["timestamp"]),
        "severity": worst["infra_status"],
        "restarts": int(sum(row["restarts"] for row in rows)),
        "oom_kills": int(sum(row["oom_kills"] for row in rows)),
    }


def classify_infrastructure_episodes(
    infra: pd.DataFrame,
    noninfra_critical_breaches: list[dict],
) -> list[dict]:
    """Classify infra episodes relative to critical breaches in other layers."""
    classified = []
    for episode in infrastructure_event_episodes(infra):
        onset = episode["onset_timestamp"]
        nearby = [
            breach
            for breach in noninfra_critical_breaches
            if abs(pd.Timestamp(breach["timestamp"]) - onset) <= pd.Timedelta(hours=3)
        ]
        prior = [
            breach
            for breach in nearby
            if pd.Timestamp(breach["timestamp"]) < onset
        ]
        if prior:
            trigger = max(prior, key=lambda breach: breach["timestamp"])
            trigger_time = pd.Timestamp(trigger["timestamp"]).strftime(
                "%b %d %H:%M UTC"
            )
            classification = "Symptom"
            reason = (
                f"Infrastructure breach began after {trigger['layer']} reached "
                f"critical at {trigger_time}."
            )
        elif not nearby:
            classification = "Isolated infra event"
            reason = "No other layer reached critical within 3 hours of the infra onset."
        else:
            trigger = min(nearby, key=lambda breach: breach["timestamp"])
            trigger_time = pd.Timestamp(trigger["timestamp"]).strftime(
                "%b %d %H:%M UTC"
            )
            classification = "Inconclusive"
            reason = (
                f"{trigger['layer']} reached critical after the infra onset, "
                f"at {trigger_time}."
            )
        classified.append(
            {
                **episode,
                "classification": classification,
                "reason": reason,
            }
        )
    return sorted(
        classified,
        key=lambda item: (item["onset_timestamp"], item["component"]),
    )
