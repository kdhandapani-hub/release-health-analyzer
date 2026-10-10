"""Overview tab: filtered layer KPIs, comparisons, health, and trends."""

import plotly.graph_objects as go
import streamlit as st

from analysis.metrics import health_for_layer, summarize


HEALTH_LABELS = {
    "healthy": ("Healthy", "health-healthy"),
    "warning": ("Warning", "health-warning"),
    "critical": ("Critical", "health-critical"),
    "unavailable": ("No data", "health-unavailable"),
}


def _delta(current, baseline, unit: str, precision: int = 1):
    if current is None or baseline is None:
        return None
    difference = current - baseline
    return f"{difference:+.{precision}f} {unit}"


def _metric(label, value, delta, delta_color="normal"):
    st.metric(
        label=label,
        value=value if value is not None else "—",
        delta=delta,
        delta_color=delta_color,
        border=True,
    )


def _layer_card(title, health, columns, content):
    label, badge_class = HEALTH_LABELS[health]
    with st.container(border=True):
        header, badge = st.columns([0.72, 0.28])
        header.markdown(f"#### {title}")
        badge.markdown(
            f'<div class="health-badge {badge_class}">● {label}</div>',
            unsafe_allow_html=True,
        )
        metric_columns = st.columns(columns)
        for column, (name, value, delta, color) in zip(metric_columns, content):
            with column:
                _metric(name, value, delta, color)


def _trend_chart(frame, value_column, title, y_title, aggregate, color):
    if frame.empty:
        return None
    hourly = frame.assign(hour=frame["timestamp"].dt.floor("h"))
    grouped = hourly.groupby("hour")[value_column].agg(aggregate).reset_index()
    figure = go.Figure(
        go.Scatter(
            x=grouped["hour"],
            y=grouped[value_column],
            mode="lines+markers",
            line={"color": color, "width": 2.5},
            marker={"size": 6},
            hovertemplate="%{x|%b %d, %H:%M} UTC<br>%{y:.2f}<extra></extra>",
        )
    )
    figure.update_layout(
        title=title,
        height=270,
        margin={"l": 8, "r": 8, "t": 46, "b": 8},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": "#d9e2f1"},
        xaxis_title="Time (UTC)",
        yaxis_title=y_title,
        showlegend=False,
    )
    figure.update_xaxes(showgrid=False)
    figure.update_yaxes(gridcolor="rgba(148,163,184,0.14)", rangemode="tozero")
    return figure


def render_overview(current, baseline):
    current_metrics = summarize(current["api"], current["kafka"], current["db"])
    baseline_metrics = summarize(baseline["api"], baseline["kafka"], baseline["db"])

    counts = {
        "API": len(current["api"]),
        "Messaging": len(current["kafka"]),
        "Database": len(current["db"]),
    }
    if not any(counts.values()):
        st.info("No data matches these filters. Adjust the sidebar filters to see results.")
        return

    st.caption(
        "Each delta compares with the preceding equal-length period. When change events "
        "are selected, the comparison is the 24 hours after each change versus the 24 hours before it."
    )

    _layer_card(
        "API",
        health_for_layer("API", current_metrics),
        2,
        [
            (
                "Pass rate (%)",
                f'{current_metrics["api_pass_rate"]:.1f}%'
                if current_metrics["api_pass_rate"] is not None else None,
                _delta(
                    current_metrics["api_pass_rate"],
                    baseline_metrics["api_pass_rate"],
                    "pp",
                ),
                "normal",
            ),
            (
                "p95 latency (ms)",
                f'{current_metrics["api_p95_latency"]:,.0f}'
                if current_metrics["api_p95_latency"] is not None else None,
                _delta(
                    current_metrics["api_p95_latency"],
                    baseline_metrics["api_p95_latency"],
                    "ms",
                    0,
                ),
                "inverse",
            ),
        ],
    )

    _layer_card(
        "Messaging",
        health_for_layer("Messaging", current_metrics),
        2,
        [
            (
                "Max consumer lag (messages)",
                f'{current_metrics["kafka_max_lag"]:,.0f}'
                if current_metrics["kafka_max_lag"] is not None else None,
                _delta(
                    current_metrics["kafka_max_lag"],
                    baseline_metrics["kafka_max_lag"],
                    "messages",
                    0,
                ),
                "inverse",
            ),
            (
                "Average error rate (%)",
                f'{current_metrics["kafka_avg_error_rate"]:.2f}%'
                if current_metrics["kafka_avg_error_rate"] is not None else None,
                _delta(
                    current_metrics["kafka_avg_error_rate"],
                    baseline_metrics["kafka_avg_error_rate"],
                    "pp",
                    2,
                ),
                "inverse",
            ),
        ],
    )

    wait_class = current_metrics["db_top_wait_class"]
    previous_wait = baseline_metrics["db_top_wait_class"]
    wait_delta = None
    if previous_wait is not None and wait_class is not None:
        wait_delta = "unchanged" if wait_class == previous_wait else f"was {previous_wait}"

    _layer_card(
        "Database",
        health_for_layer("Database", current_metrics),
        3,
        [
            (
                "Average SQL elapsed (ms)",
                f'{current_metrics["db_avg_elapsed"]:,.0f}'
                if current_metrics["db_avg_elapsed"] is not None else None,
                _delta(
                    current_metrics["db_avg_elapsed"],
                    baseline_metrics["db_avg_elapsed"],
                    "ms",
                    0,
                ),
                "inverse",
            ),
            ("Top wait class", wait_class, wait_delta, "off"),
            (
                "Active sessions (average)",
                f'{current_metrics["db_active_sessions"]:.2f}'
                if current_metrics["db_active_sessions"] is not None else None,
                _delta(
                    current_metrics["db_active_sessions"],
                    baseline_metrics["db_active_sessions"],
                    "sessions",
                    2,
                ),
                "inverse",
            ),
        ],
    )

    st.markdown("### Layer trends")
    chart_specs = (
        ("api", "latency_ms", "API p95 latency", "Latency (ms)", "quantile", "#54b7ff", 0.95),
        ("kafka", "lag", "Messaging peak lag", "Messages", "max", "#e7a94b", None),
        ("db", "avg_elapsed_ms", "Database average SQL elapsed", "Milliseconds", "mean", "#aa92ff", None),
    )
    chart_columns = st.columns(3)
    for column, (key, value, title, axis, aggregate, color, *args) in zip(chart_columns, chart_specs):
        with column:
            if aggregate == "quantile":
                frame = current[key].copy()
                if frame.empty:
                    figure = None
                else:
                    frame["_hour"] = frame["timestamp"].dt.floor("h")
                    hourly = frame.groupby("_hour")[value].quantile(args[0]).rename(value).reset_index()
                    figure = _trend_chart(
                        hourly.rename(columns={"_hour": "timestamp"}).assign(
                            timestamp=hourly["_hour"]
                        ),
                        value,
                        title,
                        axis,
                        "mean",
                        color,
                    )
            else:
                figure = _trend_chart(
                    current[key], value, title, axis, aggregate, color
                )
            if figure is None:
                st.caption(f"{title}: no matching data")
            else:
                st.plotly_chart(figure, width="stretch")
