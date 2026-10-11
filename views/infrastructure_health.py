"""Infrastructure Health tab with tier-grouped resource heatmaps and events."""

import plotly.graph_objects as go
import streamlit as st

from analysis.infrastructure import (
    classify_infrastructure_frame,
    unhealthy_infrastructure_table,
)
from analysis.thresholds import STATUS_COLORS
from views.time_axes import apply_time_axis


HEATMAP_COLORS = [
    [0.0, "#111827"],
    [0.35, "#1d4ed8"],
    [0.7, "#f59e0b"],
    [1.0, "#ef4444"],
]
TIER_ORDER = {"app": 0, "kafka": 1, "db": 2}


def _resource_heatmap(infra, metric, title, start_day, end_day):
    grouped = (
        infra.groupby(["tier", "component", "timestamp"], as_index=False, sort=True)[
            metric
        ]
        .max()
    )
    if grouped.empty:
        return None
    grouped["_tier_order"] = grouped["tier"].map(TIER_ORDER).fillna(99)
    grouped["_label"] = (
        grouped["tier"].str.title() + " · " + grouped["component"].astype(str)
    )
    labels = (
        grouped[["_tier_order", "tier", "component", "_label"]]
        .drop_duplicates()
        .sort_values(["_tier_order", "component"], kind="stable")["_label"]
        .tolist()
    )
    pivot = grouped.pivot(index="_label", columns="timestamp", values=metric)
    pivot = pivot.reindex(index=labels).sort_index(axis=1)

    figure = go.Figure(
        go.Heatmap(
            x=pivot.columns,
            y=pivot.index,
            z=pivot.to_numpy(),
            zmin=0,
            zmax=100,
            colorscale=HEATMAP_COLORS,
            colorbar={"title": "Percent", "ticksuffix": "%"},
            hovertemplate=(
                "Time: %{x|%b %d %H:%M} UTC<br>"
                "Tier / component: %{y}<br>"
                f"{title}: " + "%{z:.1f}%<extra></extra>"
            ),
        )
    )
    figure.update_layout(
        title=title,
        height=max(340, 30 * len(labels) + 130),
        margin={"l": 12, "r": 10, "t": 55, "b": 30},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": "#d9e2f1"},
        xaxis_title="Time (UTC)",
        yaxis_title="Tier · component",
    )
    apply_time_axis(figure, start_day, end_day)
    figure.update_yaxes(autorange="reversed", automargin=True)
    return figure


def _event_timeline(infra, start_day, end_day):
    event_rows = infra.loc[
        (infra["restarts"] > 0)
        | (infra["oom_kills"] > 0)
        | infra["status"].isin(["NotReady", "CrashLoopBackOff", "Degraded", "Down"])
    ].copy()
    if event_rows.empty:
        st.info("No restarts, OOM kills, or unhealthy-status events in this range.")
        return

    event_rows = classify_infrastructure_frame(event_rows)
    event_rows["asset"] = (
        event_rows["tier"].str.title()
        + " · "
        + event_rows["component"].astype(str)
        + " · "
        + event_rows["node"].astype(str)
    )
    event_rows["size"] = (
        13
        + event_rows["restarts"].clip(lower=0) * 3
        + event_rows["oom_kills"].clip(lower=0) * 3
    )
    event_rows["color"] = event_rows["infra_status"].map(STATUS_COLORS)
    figure = go.Figure(
        go.Scatter(
            x=event_rows["timestamp"],
            y=event_rows["asset"],
            mode="markers",
            marker={
                "size": event_rows["size"],
                "color": event_rows["color"],
                "line": {"color": "#f8fafc", "width": 0.8},
            },
            customdata=event_rows[
                ["restarts", "oom_kills", "status", "infra_status", "pod"]
            ],
            hovertemplate=(
                "%{x|%b %d %H:%M} UTC<br>%{y}<br>"
                "Restarts: %{customdata[0]}<br>"
                "OOM kills: %{customdata[1]}<br>"
                "Raw status: %{customdata[2]}<br>"
                "Health: %{customdata[3]}<br>"
                "Pod: %{customdata[4]}<extra></extra>"
            ),
            name="Restart / OOM / status event",
        )
    )
    figure.update_layout(
        title="Restart, OOM, and unhealthy-status timeline",
        height=max(300, 75 * event_rows["asset"].nunique() + 120),
        margin={"l": 12, "r": 15, "t": 55, "b": 35},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": "#d9e2f1"},
        xaxis_title="Time (UTC)",
        yaxis_title="Tier · component · node",
        showlegend=False,
    )
    apply_time_axis(figure, start_day, end_day)
    figure.update_yaxes(autorange="reversed", automargin=True)
    st.plotly_chart(figure, width="stretch")


def render_infrastructure_health(infra, start_day, end_day):
    """Render resource heatmaps, host events, and unhealthy assets."""
    st.subheader("Infrastructure health")
    if infra.empty:
        st.info("No infrastructure metrics match these filters.")
        return

    st.caption(
        "Resource heatmaps show the maximum pod value per service and hour; "
        "all values are percentages and retain tier grouping."
    )
    columns = st.columns(3)
    metrics = (
        ("cpu_pct", "CPU utilization (%)"),
        ("memory_pct", "Memory utilization (%)"),
        ("io_wait_pct", "I/O wait (%)"),
    )
    for column, (metric, title) in zip(columns, metrics):
        with column:
            figure = _resource_heatmap(infra, metric, title, start_day, end_day)
            if figure is None:
                st.caption(f"{title}: no samples")
            else:
                st.plotly_chart(figure, width="stretch")

    st.subheader("Restart and OOM events")
    _event_timeline(infra, start_day, end_day)

    st.subheader("Unhealthy pods and hosts")
    unhealthy = unhealthy_infrastructure_table(infra)
    if unhealthy.empty:
        st.info("No pods or hosts crossed an infrastructure warning threshold.")
    else:
        st.dataframe(unhealthy, hide_index=True, width="stretch")
