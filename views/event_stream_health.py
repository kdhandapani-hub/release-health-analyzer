"""Event Stream Health tab."""

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from analysis.stream_metrics import (
    consumer_group_lag_summary,
    error_rate_by_topic,
    lag_heatmap_matrix,
    throughput_by_topic,
)
from analysis.thresholds import (
    KAFKA_ERROR_RATE_CRITICAL_PCT,
    KAFKA_ERROR_RATE_WARNING_PCT,
    KAFKA_LAG_CRITICAL_MESSAGES,
    STATUS_COLORS,
)


CHART_LAYOUT = {
    "paper_bgcolor": "rgba(0,0,0,0)",
    "plot_bgcolor": "rgba(0,0,0,0)",
    "font": {"color": "#d9e2f1"},
    "margin": {"l": 12, "r": 18, "t": 55, "b": 18},
}
SIX_HOURS_MS = 6 * 60 * 60 * 1000


def _time_axis(figure):
    figure.update_xaxes(
        title="Time (UTC)",
        type="date",
        tickmode="linear",
        dtick=SIX_HOURS_MS,
        tickformat="%b %d<br>%H:%M",
        tickangle=-45,
        showgrid=False,
    )


def _lag_heatmap(kafka):
    matrix = lag_heatmap_matrix(kafka)
    if matrix.empty:
        st.info("No lag samples match these filters.")
        return

    figure = go.Figure(
        go.Heatmap(
            z=matrix.to_numpy(),
            x=matrix.columns,
            y=matrix.index,
            zmin=0,
            zmax=KAFKA_LAG_CRITICAL_MESSAGES,
            colorscale=[
                [0.0, "#101a2b"],
                [0.12, "#1d4ed8"],
                [0.4, "#38bdf8"],
                [0.72, "#f59e0b"],
                [1.0, STATUS_COLORS["critical"]],
            ],
            colorbar={"title": "Lag (messages)"},
            hovertemplate=(
                "Time: %{x|%b %d, %H:%M} UTC<br>"
                "Topic / partition: %{y}<br>"
                "Lag: %{z:,.0f} messages<extra></extra>"
            ),
        )
    )
    figure.update_layout(
        **CHART_LAYOUT,
        title="Consumer lag by topic and partition",
        height=max(420, len(matrix.index) * 27),
        xaxis_title="Time (UTC)",
        yaxis_title="Topic / partition",
    )
    _time_axis(figure)
    figure.update_yaxes(automargin=True, showgrid=False)
    st.caption(
        f"Heatmap scale runs from neutral/cool to critical red at "
        f"{KAFKA_LAG_CRITICAL_MESSAGES:,} messages; higher lag saturates at red."
    )
    st.plotly_chart(figure, width="stretch")


def _throughput_chart(kafka):
    throughput = throughput_by_topic(kafka)
    if throughput.empty:
        st.info("No throughput samples match these filters.")
        return

    figure = px.line(
        throughput,
        x="timestamp",
        y="msgs_per_sec",
        color="topic",
        title="Throughput by topic over time",
        labels={
            "timestamp": "Time (UTC)",
            "msgs_per_sec": "Throughput (messages/sec)",
            "topic": "Topic",
        },
    )
    figure.update_layout(**CHART_LAYOUT, height=390, legend_title_text="Topic")
    figure.update_yaxes(
        title="Throughput (messages/sec)",
        rangemode="tozero",
        gridcolor="rgba(148,163,184,0.14)",
    )
    _time_axis(figure)
    st.plotly_chart(figure, width="stretch")


def _consumer_group_table(kafka):
    groups = consumer_group_lag_summary(kafka)
    if groups.empty:
        st.info("No consumer groups match these filters.")
        return

    st.caption("Group status is based on max lag and the shared messaging thresholds.")
    display = groups.rename(
        columns={
            "consumer_group": "Consumer group",
            "max_lag": "Max lag (messages)",
            "avg_lag": "Avg lag (messages)",
            "peak_time": "Peak time (UTC)",
            "status": "Status",
        }
    )
    display["Max lag (messages)"] = display["Max lag (messages)"].round(0).astype(int)
    display["Avg lag (messages)"] = display["Avg lag (messages)"].round(1)
    display["Peak time (UTC)"] = display["Peak time (UTC)"].dt.strftime(
        "%Y-%m-%d %H:%M"
    )

    def status_style(status):
        color = STATUS_COLORS.get(status.lower(), STATUS_COLORS["unavailable"])
        return f"background-color: {color}; color: #0b1220; font-weight: 700"

    styled = display.style.map(status_style, subset=["Status"])
    st.dataframe(styled, hide_index=True, width="stretch")


def _error_rate_chart(kafka):
    error_rates = error_rate_by_topic(kafka)
    if error_rates.empty:
        st.info("No error-rate samples match these filters.")
        return

    figure = px.line(
        error_rates,
        x="timestamp",
        y="error_rate_pct",
        color="topic",
        title="Error rate by topic over time",
        labels={
            "timestamp": "Time (UTC)",
            "error_rate_pct": "Error rate (%)",
            "topic": "Topic",
        },
    )
    for threshold, status, label in (
        (
            KAFKA_ERROR_RATE_WARNING_PCT,
            "warning",
            f"Warning {KAFKA_ERROR_RATE_WARNING_PCT:g}%",
        ),
        (
            KAFKA_ERROR_RATE_CRITICAL_PCT,
            "critical",
            f"Critical {KAFKA_ERROR_RATE_CRITICAL_PCT:g}%",
        ),
    ):
        figure.add_hline(
            y=threshold,
            line_dash="dash",
            line_width=2,
            line_color=STATUS_COLORS[status],
            annotation_text=label,
            annotation_position="top left",
            annotation_font_color=STATUS_COLORS[status],
        )

    y_max = max(
        float(error_rates["error_rate_pct"].max()),
        KAFKA_ERROR_RATE_CRITICAL_PCT,
    )
    figure.update_layout(**CHART_LAYOUT, height=410, legend_title_text="Topic")
    figure.update_yaxes(
        title="Error rate (%)",
        range=[0, y_max * 1.1],
        gridcolor="rgba(148,163,184,0.14)",
    )
    _time_axis(figure)
    st.plotly_chart(figure, width="stretch")


def render_event_stream_health(kafka):
    if kafka.empty:
        st.info(
            "No event-stream metrics match these filters. Adjust the sidebar filters to see results."
        )
        return

    _lag_heatmap(kafka)
    st.subheader("Throughput")
    _throughput_chart(kafka)
    st.subheader("Top lagging consumer groups")
    _consumer_group_table(kafka)
    st.subheader("Error rate")
    _error_rate_chart(kafka)
