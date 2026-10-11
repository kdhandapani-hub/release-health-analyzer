"""API Test Results tab."""

import plotly.express as px
import streamlit as st

from analysis.api_metrics import (
    failure_reason_breakdown,
    latency_percentiles,
    p95_latency_over_time_by_service,
    pass_rate_by_endpoint,
    pass_rate_by_service,
    release_comparison,
)
from analysis.thresholds import (
    API_PASS_RATE_SLA_PCT,
    API_P95_CRITICAL_MS,
    STATUS_COLORS,
    classify_api_pass_rate,
)
from views.time_axes import apply_time_axis


CHART_LAYOUT = {
    "paper_bgcolor": "rgba(0,0,0,0)",
    "plot_bgcolor": "rgba(0,0,0,0)",
    "font": {"color": "#d9e2f1"},
    "margin": {"l": 8, "r": 20, "t": 55, "b": 12},
}

def _pass_rate_chart(frame, title, group_label):
    figure = px.bar(
        frame,
        x="pass_rate_pct",
        y="group",
        orientation="h",
        text="pass_rate_pct",
        hover_data={"run_count": True, "pass_rate_pct": ":.2f"},
        labels={
            "pass_rate_pct": "Pass rate (%)",
            "group": group_label,
            "run_count": "Runs (count)",
        },
        title=title,
    )
    figure.update_traces(
        marker_color=[
            STATUS_COLORS[classify_api_pass_rate(rate)]
            for rate in frame["pass_rate_pct"]
        ],
        texttemplate="%{x:.1f}%",
        textposition="outside",
        cliponaxis=False,
    )
    figure.add_vline(
        x=API_PASS_RATE_SLA_PCT,
        line_color="#fcd34d",
        line_dash="dash",
        line_width=2,
        annotation_text=f"SLA {API_PASS_RATE_SLA_PCT:g}%",
        annotation_position="top",
        annotation_font_color="#fcd34d",
    )
    figure.update_layout(**CHART_LAYOUT, height=max(300, len(frame) * 34))
    figure.update_xaxes(
        title="Pass rate (%)",
        range=[0, 105],
        gridcolor="rgba(148,163,184,0.14)",
    )
    figure.update_yaxes(title=group_label, automargin=True, showgrid=False)
    return figure


def _format_delta(value, suffix, precision=1):
    if value is None or not value == value:
        return "—"
    return f"{value:+,.{precision}f} {suffix}"


def _p95_latency_chart(api, start_day, end_day):
    trend = p95_latency_over_time_by_service(api)
    figure = px.line(
        trend,
        x="timestamp",
        y="p95_latency_ms",
        color="service",
        markers=True,
        labels={
            "timestamp": "Time (UTC)",
            "p95_latency_ms": "p95 latency (ms)",
            "service": "Service",
        },
        title="p95 latency over time by service",
    )
    figure.add_hline(
        y=API_P95_CRITICAL_MS,
        line_color=STATUS_COLORS["critical"],
        line_dash="dash",
        line_width=2,
        annotation_text=f"Critical {API_P95_CRITICAL_MS:,.0f} ms",
        annotation_position="top left",
        annotation_font_color=STATUS_COLORS["critical"],
    )
    figure.update_traces(
        hovertemplate=(
            "%{x|%b %d, %H:%M} UTC<br>Service: %{fullData.name}"
            "<br>p95 latency: %{y:,.1f} ms<extra></extra>"
        )
    )
    figure.update_layout(**CHART_LAYOUT, height=390, hovermode="x unified")
    figure.update_xaxes(title="Time (UTC)")
    figure.update_yaxes(
        title="p95 latency (ms)",
        rangemode="tozero",
        gridcolor="rgba(148,163,184,0.14)",
    )
    apply_time_axis(figure, start_day, end_day)
    return figure


def render_api_test_results(api, start_day, end_day):
    if api.empty:
        st.info("No API test runs match these filters. Adjust the sidebar filters to see results.")
        return

    service_rates = pass_rate_by_service(api)
    endpoint_rates = pass_rate_by_endpoint(api)
    percentiles = latency_percentiles(api)
    failures = failure_reason_breakdown(api)
    releases = release_comparison(api)

    st.subheader("Pass rate")
    service_column, endpoint_column = st.columns(2)
    with service_column:
        st.plotly_chart(
            _pass_rate_chart(service_rates, "Pass rate by service", "Service"),
            width="stretch",
        )
    with endpoint_column:
        st.plotly_chart(
            _pass_rate_chart(endpoint_rates, "Pass rate by endpoint", "Endpoint"),
            width="stretch",
        )

    st.subheader("Latency distribution")
    percentile_columns = st.columns(3)
    for column, row in zip(percentile_columns, percentiles.itertuples(index=False)):
        column.metric(f"{row.percentile} latency (ms)", f"{row.latency_ms:,.0f} ms")

    st.plotly_chart(
        _p95_latency_chart(api, start_day, end_day),
        width="stretch",
    )

    st.subheader("Failure reasons")
    if failures.empty:
        st.info("No failed API runs match these filters.")
    else:
        failures = failures.sort_values("failed_runs", ascending=True, kind="stable")
        failures["label"] = failures.apply(
            lambda row: f'{row["failed_runs"]:,} · {row["failure_pct"]:.1f}%', axis=1
        )
        failure_chart = px.bar(
            failures,
            x="failed_runs",
            y="failure_reason",
            orientation="h",
            text="label",
            custom_data=["failure_pct"],
            labels={
                "failed_runs": "Failed runs (count)",
                "failure_reason": "Failure reason",
                "failure_pct": "Share of failures (%)",
            },
            title="Failure reasons by failed-run count and share",
        )
        failure_chart.update_traces(
            marker_color="#ef7385",
            textposition="outside",
            cliponaxis=False,
            hovertemplate=(
                "Reason: %{y}<br>Failed runs: %{x:,}"
                "<br>Share of failures: %{customdata[0]:.1f}%<extra></extra>"
            ),
        )
        failure_chart.update_layout(
            **CHART_LAYOUT,
            height=max(300, len(failures) * 42),
            margin={"l": 8, "r": 100, "t": 55, "b": 12},
        )
        failure_chart.update_xaxes(
            title="Failed runs (count)",
            range=[0, max(1, float(failures["failed_runs"].max()) * 1.35)],
            gridcolor="rgba(148,163,184,0.14)",
        )
        failure_chart.update_yaxes(
            title="Failure reason", automargin=True, showgrid=False
        )
        st.plotly_chart(failure_chart, width="stretch")

    st.subheader("Release-over-release comparison")
    st.caption("Each delta is compared with the immediately previous release in the selected range.")
    display_rows = []
    for row in releases.itertuples(index=False):
        display_rows.append(
            {
                "Release": row.release_tag,
                "Runs (count)": f"{row.run_count:,}",
                "Pass rate (%)": f"{row.pass_rate_pct:.2f}%",
                "Δ pass rate (pp)": _format_delta(row.pass_rate_delta_pp, "pp", 2),
                "p95 latency (ms)": f"{row.p95_latency_ms:,.0f} ms",
                "Δ p95 latency (ms)": _format_delta(row.p95_delta_ms, "ms", 0),
            }
        )
    st.dataframe(display_rows, hide_index=True, width="stretch")
