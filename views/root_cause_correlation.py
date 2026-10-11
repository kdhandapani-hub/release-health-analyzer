"""Root Cause Correlation tab."""

from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from analysis.root_cause import analyze_root_cause
from analysis.thresholds import (
    API_FAILURE_RATE_CRITICAL_PCT,
    API_FAILURE_RATE_WARNING_PCT,
    API_P95_CRITICAL_MS,
    API_P95_WARNING_MS,
    DB_ELAPSED_CRITICAL_MS,
    DB_ELAPSED_WARNING_MS,
    KAFKA_LAG_CRITICAL_MESSAGES,
    KAFKA_LAG_WARNING_MESSAGES,
    STATUS_COLORS,
)
from views.time_axes import apply_time_axis


CHART_LAYOUT = {
    "paper_bgcolor": "rgba(0,0,0,0)",
    "plot_bgcolor": "rgba(0,0,0,0)",
    "font": {"color": "#d9e2f1"},
    "margin": {"l": 20, "r": 30, "t": 95, "b": 40},
}

TRACE_COLORS = {
    "db_average": "#60a5fa",
    "db_slowest": "#fb7185",
    "api_failure": "#ef4444",
    "api_p95": "#f97316",
    "messaging_lag": "#a78bfa",
}


def _format_time(timestamp, start_day, end_day):
    stamp = pd.Timestamp(timestamp)
    if (end_day - start_day).days == 0:
        return stamp.strftime("%H:%M UTC")
    return stamp.strftime("%b %-d %H:%M UTC")


def _format_duration(delta):
    seconds = max(0, int(delta.total_seconds()))
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours} hour" if hours == 1 else f"{hours} hours"
    return f"{minutes} minutes"


def _render_summary(analysis, start_day, end_day):
    st.subheader("Correlation summary")
    first_breach = analysis["first_breach"]
    trigger = analysis["trigger"]
    with st.container(border=True):
        if first_breach is None:
            st.info("No correlated degradation in this range.")
            st.caption(
                "No filtered layer reached its critical threshold during the selected range."
            )
        else:
            first_time = first_breach["timestamp"]
            trigger_label = (
                f"{trigger['change_id']} · {trigger['change_type']} · "
                f"{_format_time(trigger['timestamp'], start_day, end_day)}"
                if trigger
                else "No preceding change event in this range"
            )
            first_label = (
                f"{first_breach['layer']} · "
                f"{_format_time(first_time, start_day, end_day)}"
            )
            sequence = " → ".join(
                f"{item['layer']} {_format_time(item['timestamp'], start_day, end_day)}"
                for item in analysis["sequence"]
            )
            elapsed = (
                _format_duration(first_time - trigger["timestamp"])
                if trigger
                else "Unavailable"
            )
            cols = st.columns(3)
            cols[0].markdown("**Likely trigger**")
            cols[0].write(trigger_label)
            cols[1].markdown("**First layer to degrade**")
            cols[1].write(first_label)
            cols[2].markdown("**Change to first breach**")
            cols[2].write(elapsed)
            st.markdown(f"**Critical-breach sequence:** {sequence}")

        assessments = analysis["event_assessments"]
        cleared = [event for event in assessments if event["status"] == "cleared"]
        inconclusive = [
            event for event in assessments if event["status"] == "inconclusive"
        ]
        if cleared:
            st.markdown("**Cleared changes**")
            for event in cleared:
                time = _format_time(event["timestamp"], start_day, end_day)
                st.markdown(
                    f"- `{event['change_id']}` — cleared at {time}; {event['reason']}"
                )
        if inconclusive:
            st.markdown("**Inconclusive changes**")
            for event in inconclusive:
                time = _format_time(event["timestamp"], start_day, end_day)
                st.markdown(
                    f"- `{event['change_id']}` — inconclusive at {time}; {event['reason']}"
                )
        if not cleared and not inconclusive:
            st.caption("No other change events fall within this selected range.")


def _add_threshold(
    figure,
    value,
    status,
    row,
    col=1,
    secondary_y=False,
):
    figure.add_hline(
        y=value,
        line_dash="dash",
        line_width=1.5,
        line_color=STATUS_COLORS[status],
        row=row,
        col=col,
        secondary_y=secondary_y,
    )


def _add_breach_shading(figure, frame, row):
    if frame.empty:
        return
    samples = frame.sort_values("timestamp", kind="stable").reset_index(drop=True)
    active_start = None
    active_status = None
    previous_time = None
    periods = []

    for sample in samples.itertuples(index=False):
        status = sample.status
        timestamp = sample.timestamp
        if status not in ("warning", "critical"):
            if active_start is not None:
                periods.append((active_start, previous_time + pd.Timedelta(hours=1), active_status))
                active_start = active_status = None
            previous_time = timestamp
            continue
        if active_start is None:
            active_start, active_status = timestamp, status
        elif status != active_status or timestamp != previous_time + pd.Timedelta(hours=1):
            periods.append((active_start, previous_time + pd.Timedelta(hours=1), active_status))
            active_start, active_status = timestamp, status
        previous_time = timestamp

    if active_start is not None:
        periods.append((active_start, previous_time + pd.Timedelta(hours=1), active_status))

    for start, end, status in periods:
        figure.add_vrect(
            x0=start,
            x1=end,
            fillcolor=STATUS_COLORS[status],
            opacity=0.20 if status == "warning" else 0.28,
            line_width=0,
            layer="below",
            row=row,
            col=1,
        )


def _add_event_markers(figure, changes):
    if changes.empty:
        return
    for event in changes.itertuples(index=False):
        for row in (1, 2, 3):
            figure.add_vline(
                x=event.timestamp,
                line_dash="dot",
                line_width=1.4,
                line_color=STATUS_COLORS["warning"],
                annotation_text=event.change_id,
                annotation_position="top left",
                annotation_font_color=STATUS_COLORS["warning"],
                annotation_textangle=-90,
                row=row,
                col=1,
            )


def _add_thresholds(figure):
    for value, status in (
        (DB_ELAPSED_WARNING_MS, "warning"),
        (DB_ELAPSED_CRITICAL_MS, "critical"),
    ):
        _add_threshold(figure, value, status, row=1)

    for value, status in (
        (API_FAILURE_RATE_WARNING_PCT, "warning"),
        (API_FAILURE_RATE_CRITICAL_PCT, "critical"),
    ):
        _add_threshold(figure, value, status, row=2)
    for value, status in (
        (API_P95_WARNING_MS, "warning"),
        (API_P95_CRITICAL_MS, "critical"),
    ):
        _add_threshold(
            figure,
            value,
            status,
            row=2,
            secondary_y=True,
        )

    for value, status in (
        (KAFKA_LAG_WARNING_MESSAGES, "warning"),
        (KAFKA_LAG_CRITICAL_MESSAGES, "critical"),
    ):
        _add_threshold(figure, value, status, row=3)


def _render_chart(analysis, changes, start_day, end_day):
    lanes = analysis["lanes"]
    if all(frame.empty for frame in lanes.values()):
        st.info(
            "No database, API, or messaging metrics match these filters. "
            "Adjust the sidebar filters to see results."
        )
        return

    figure = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.34, 0.33, 0.33],
        specs=[[{}], [{"secondary_y": True}], [{}]],
        subplot_titles=(
            "Database · SQL elapsed time",
            "API · failure rate and p95 latency",
            "Messaging · maximum consumer lag",
        ),
    )
    for row, layer in enumerate(("Database", "API", "Messaging"), start=1):
        _add_breach_shading(figure, lanes[layer], row)

    db = lanes["Database"]
    if not db.empty:
        figure.add_trace(
            go.Scatter(
                x=db["timestamp"],
                y=db["slowest_sql_elapsed_ms"],
                customdata=db["slowest_sql_id"],
                mode="lines+markers",
                name="Slowest SQL elapsed",
                line={"color": TRACE_COLORS["db_slowest"], "width": 2.5},
                hovertemplate=(
                    "%{x|%b %d %H:%M} UTC<br>Slowest SQL: %{customdata}"
                    "<br>Elapsed: %{y:.1f} ms<extra></extra>"
                ),
            ),
            row=1,
            col=1,
        )
        figure.add_trace(
            go.Scatter(
                x=db["timestamp"],
                y=db["avg_elapsed_ms"],
                mode="lines+markers",
                name="Average elapsed",
                line={"color": TRACE_COLORS["db_average"], "width": 2},
                hovertemplate=(
                    "%{x|%b %d %H:%M} UTC<br>Average elapsed: "
                    "%{y:.1f} ms<extra></extra>"
                ),
            ),
            row=1,
            col=1,
        )

    api = lanes["API"]
    if not api.empty:
        figure.add_trace(
            go.Scatter(
                x=api["timestamp"],
                y=api["failure_rate_pct"],
                mode="lines+markers",
                name="API failure rate",
                line={"color": TRACE_COLORS["api_failure"], "width": 2.3},
                hovertemplate=(
                    "%{x|%b %d %H:%M} UTC<br>Failure rate: "
                    "%{y:.2f}%<extra></extra>"
                ),
            ),
            row=2,
            col=1,
            secondary_y=False,
        )
        figure.add_trace(
            go.Scatter(
                x=api["timestamp"],
                y=api["p95_latency_ms"],
                mode="lines+markers",
                name="API p95 latency",
                line={"color": TRACE_COLORS["api_p95"], "width": 2.3},
                hovertemplate=(
                    "%{x|%b %d %H:%M} UTC<br>p95 latency: "
                    "%{y:.1f} ms<extra></extra>"
                ),
            ),
            row=2,
            col=1,
            secondary_y=True,
        )

    messaging = lanes["Messaging"]
    if not messaging.empty:
        figure.add_trace(
            go.Scatter(
                x=messaging["timestamp"],
                y=messaging["max_lag"],
                mode="lines+markers",
                name="Maximum consumer lag",
                line={"color": TRACE_COLORS["messaging_lag"], "width": 2.4},
                hovertemplate=(
                    "%{x|%b %d %H:%M} UTC<br>Maximum consumer lag: "
                    "%{y:,.0f} messages<extra></extra>"
                ),
            ),
            row=3,
            col=1,
        )

    _add_thresholds(figure)
    _add_event_markers(figure, changes)
    db_y_max = max(
        float(db["slowest_sql_elapsed_ms"].max()) if not db.empty else 0.0,
        DB_ELAPSED_CRITICAL_MS,
    ) * 1.1
    api_failure_y_max = max(
        float(api["failure_rate_pct"].max()) if not api.empty else 0.0,
        API_FAILURE_RATE_CRITICAL_PCT,
    ) * 1.15
    api_p95_y_max = max(
        float(api["p95_latency_ms"].max()) if not api.empty else 0.0,
        API_P95_CRITICAL_MS,
    ) * 1.1
    messaging_y_max = max(
        float(messaging["max_lag"].max()) if not messaging.empty else 0.0,
        KAFKA_LAG_CRITICAL_MESSAGES,
    ) * 1.1
    figure.update_layout(
        **CHART_LAYOUT,
        height=1010,
        hovermode="x unified",
        legend={"orientation": "h", "y": 1.12, "x": 1, "xanchor": "right"},
    )
    figure.update_yaxes(
        title_text="Elapsed time (ms)",
        range=[0, db_y_max],
        gridcolor="rgba(148,163,184,.14)",
        row=1,
        col=1,
    )
    figure.update_yaxes(
        title_text="Failure rate (%)",
        range=[0, api_failure_y_max],
        gridcolor="rgba(148,163,184,.14)",
        row=2,
        col=1,
        secondary_y=False,
    )
    figure.update_yaxes(
        title_text="p95 latency (ms)",
        range=[0, api_p95_y_max],
        showgrid=False,
        row=2,
        col=1,
        secondary_y=True,
    )
    figure.update_yaxes(
        title_text="Max lag (messages)",
        range=[0, messaging_y_max],
        gridcolor="rgba(148,163,184,.14)",
        row=3,
        col=1,
    )
    apply_time_axis(figure, start_day, end_day)
    missing_layers = [
        layer for layer, frame in lanes.items() if frame.empty
    ]
    if missing_layers:
        st.caption(
            "No samples for these filtered layers: " + ", ".join(missing_layers) + "."
        )
    st.caption(
        f"Dashed thresholds (warning / critical): DB elapsed "
        f"{DB_ELAPSED_WARNING_MS:g}/{DB_ELAPSED_CRITICAL_MS:g} ms; API failures "
        f"{API_FAILURE_RATE_WARNING_PCT:g}/{API_FAILURE_RATE_CRITICAL_PCT:g}%; "
        f"API p95 {API_P95_WARNING_MS:g}/{API_P95_CRITICAL_MS:g} ms; messaging lag "
        f"{KAFKA_LAG_WARNING_MESSAGES:,}/{KAFKA_LAG_CRITICAL_MESSAGES:,} messages. "
        "Amber shading marks warning periods; red shading marks critical periods."
    )
    st.plotly_chart(figure, width="stretch")


def render_root_cause_correlation(
    api,
    kafka,
    db,
    changes,
    start_day,
    end_day,
    selected_event_ids=None,
):
    """Render deterministic cross-layer analysis for the current sidebar filters."""
    analysis = analyze_root_cause(
        api,
        kafka,
        db,
        changes,
        start_day,
        end_day,
        selected_event_ids=selected_event_ids or [],
    )
    _render_summary(analysis, start_day, end_day)
    _render_chart(analysis, analysis["changes"], start_day, end_day)
