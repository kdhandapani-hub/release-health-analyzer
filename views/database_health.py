"""Database Health tab: DB time, SQL latency, waits, and plan regressions."""

import html

import plotly.graph_objects as go
import pandas as pd
import streamlit as st

from analysis.database_metrics import (
    db_time_by_connection_user,
    detect_plan_regressions,
    sql_elapsed_trend,
    top_sql_summary,
    wait_class_percent_over_time,
)
from analysis.thresholds import (
    DB_ELAPSED_CRITICAL_MS,
    DB_ELAPSED_WARNING_MS,
    STATUS_COLORS,
)
from views.time_axes import apply_time_axis


CHART_LAYOUT = {
    "paper_bgcolor": "rgba(0,0,0,0)",
    "plot_bgcolor": "rgba(0,0,0,0)",
    "font": {"color": "#d9e2f1"},
    "margin": {"l": 12, "r": 20, "t": 58, "b": 18},
}

WAIT_COLORS = {
    "CPU": "#60a5fa",
    "User I/O": STATUS_COLORS["critical"],
    "Concurrency": "#a78bfa",
    "Commit": STATUS_COLORS["healthy"],
    "Application": STATUS_COLORS["warning"],
}


def _db_time_chart(db):
    grouped = db_time_by_connection_user(db)
    if grouped.empty:
        st.info("No database time matches these filters.")
        return
    figure = go.Figure()
    for caller_type in ("API", "Consumer"):
        caller = grouped[grouped["caller_type"] == caller_type]
        if caller.empty:
            continue
        figure.add_trace(
            go.Bar(
                x=caller["service"],
                y=caller["db_time_sec"],
                name=caller_type,
                customdata=caller["db_user"],
                hovertemplate=(
                    "Service: %{x}<br>Connection user: %{customdata}"
                    "<br>DB time: %{y:,.2f} seconds<extra></extra>"
                ),
            )
        )
    figure.update_layout(
        **CHART_LAYOUT,
        title="DB time by connection user and caller type",
        height=410,
        barmode="stack",
        legend_title_text="Caller type",
    )
    figure.update_xaxes(title="Service", showgrid=False)
    figure.update_yaxes(
        title="Total elapsed DB time (seconds)",
        rangemode="tozero",
        gridcolor="rgba(148,163,184,0.14)",
    )
    st.plotly_chart(figure, width="stretch")


def _top_sql_table(db):
    summary = top_sql_summary(db).head(10)
    if summary.empty:
        st.info("No SQL activity matches these filters.")
        return
    st.caption(
        "Max elapsed is the highest hourly average in the source data; "
        "the synthetic CSV does not contain per-execution maximums."
    )
    headers = (
        "SQL ID",
        "DB user(s)",
        "SQL type",
        "Executions",
        "Avg elapsed (ms)",
        "Max elapsed (ms)",
        "Top wait class",
        "Status",
    )
    widths = ("8%", "26%", "8%", "10%", "12%", "12%", "14%", "10%")
    header_html = "".join(
        f'<th scope="col" style="width:{width}">{html.escape(header)}</th>'
        for header, width in zip(headers, widths)
    )
    rows_html = []
    for row in summary.itertuples(index=False):
        status = str(row.status).lower()
        status_color = STATUS_COLORS.get(status, STATUS_COLORS["unavailable"])
        cells = (
            html.escape(str(row.sql_id)),
            html.escape(str(row.db_users)),
            html.escape(str(row.sql_type)),
            f"{row.executions:,}",
            f"{row.avg_elapsed_ms:,.1f}",
            f"{row.max_elapsed_ms:,.1f}",
            html.escape(str(row.top_wait_class)),
        )
        data_cells = "".join(
            "<td>"
            f'<div style="overflow-wrap:anywhere">{value}</div>'
            "</td>"
            for value in cells
        )
        data_cells += (
            "<td>"
            f'<span style="display:inline-block;padding:3px 8px;border-radius:999px;'
            f'background:{status_color};color:#0b1220;font-weight:700">'
            f"{html.escape(status.title())}</span>"
            "</td>"
        )
        rows_html.append(f"<tr>{data_cells}</tr>")
    st.markdown(
        """
        <style>
          .db-sql-table-wrap { overflow-x: auto; }
          .db-sql-table {
            width: 100%; min-width: 900px; table-layout: fixed;
            border-collapse: collapse; color: #d9e2f1; font-size: .82rem;
          }
          .db-sql-table th, .db-sql-table td {
            border: 1px solid rgba(148,163,184,.18);
            padding: 8px 7px; text-align: left; vertical-align: middle;
          }
          .db-sql-table th {
            color: #b7c5d8; font-weight: 600; white-space: normal;
            background: rgba(23,36,56,.56);
          }
        </style>
        <div class="db-sql-table-wrap">
          <table class="db-sql-table">
            <thead><tr>
        """
        + header_html
        + "</tr></thead><tbody>"
        + "".join(rows_html)
        + "</tbody></table></div>",
        unsafe_allow_html=True,
    )


def _add_change_markers(figure, changes, start_day, end_day, selected_event_ids):
    if changes.empty:
        return
    start = start_day.isoformat()
    end = end_day.isoformat()
    in_range = changes["timestamp"].dt.strftime("%Y-%m-%d").between(start, end)
    events = changes[in_range]
    if selected_event_ids:
        events = events[events["change_id"].isin(selected_event_ids)]
    for event in events.itertuples(index=False):
        figure.add_vline(
            x=event.timestamp,
            line_dash="dash",
            line_width=1.5,
            line_color=STATUS_COLORS["warning"],
        )
        figure.add_annotation(
            x=event.timestamp,
            y=1.0,
            xref="x",
            yref="paper",
            text=event.change_id,
            showarrow=False,
            textangle=-90,
            xanchor="left",
            yanchor="top",
            font={"color": STATUS_COLORS["warning"], "size": 10},
        )


def _elapsed_trend(db, changes, start_day, end_day, selected_event_ids):
    trend = sql_elapsed_trend(db)
    if trend.empty:
        st.info("No SQL elapsed-time samples match these filters.")
        return
    ranking = (
        trend.groupby("sql_id")["db_time_ms"]
        .sum()
        .sort_values(ascending=False, kind="stable")
    )
    top_sql_ids = ranking.index[:5].tolist()
    figure = go.Figure()
    for sql_id in ranking.index:
        series = trend[trend["sql_id"] == sql_id]
        is_top = sql_id in top_sql_ids
        figure.add_trace(
            go.Scatter(
                x=series["timestamp"],
                y=series["avg_elapsed_ms"],
                mode="lines+markers",
                name=sql_id,
                visible=True if is_top else "legendonly",
                line={
                    "width": 2.4 if is_top else 1.5,
                    "color": STATUS_COLORS["critical"] if sql_id == "PAYQRY01" else None,
                },
                marker={"size": 5},
                customdata=series["db_time_ms"],
                hovertemplate=(
                    "%{x|%b %d, %H:%M} UTC<br>SQL ID: %{fullData.name}"
                    "<br>Avg elapsed: %{y:.1f} ms"
                    "<br>DB time: %{customdata:,.0f} ms<extra></extra>"
                ),
            )
        )
    for threshold, status, label in (
        (DB_ELAPSED_WARNING_MS, "warning", f"Warning {DB_ELAPSED_WARNING_MS:g} ms"),
        (DB_ELAPSED_CRITICAL_MS, "critical", f"Critical {DB_ELAPSED_CRITICAL_MS:g} ms"),
    ):
        figure.add_hline(
            y=threshold,
            line_dash="dash",
            line_width=1.5,
            line_color=STATUS_COLORS[status],
            annotation_text=label,
            annotation_position="top left",
            annotation_font_color=STATUS_COLORS[status],
        )
    _add_change_markers(
        figure, changes, start_day, end_day, selected_event_ids
    )
    figure.update_layout(
        **CHART_LAYOUT,
        title="Average elapsed time by SQL ID",
        height=470,
        legend_title_text="Top 5 shown · click legend for other SQL",
    )
    figure.update_xaxes(title="Time (UTC)")
    figure.update_yaxes(
        title="Average elapsed per execution (ms)",
        rangemode="tozero",
        gridcolor="rgba(148,163,184,0.14)",
    )
    apply_time_axis(figure, start_day, end_day)
    st.caption(
        "Top five SQL IDs by total DB time are shown; other SQL IDs are hidden by default and available in the legend."
    )
    st.plotly_chart(figure, width="stretch")


def _wait_class_trend(db, changes, start_day, end_day, selected_event_ids):
    breakdown = wait_class_percent_over_time(db)
    if breakdown.empty:
        st.info("No wait-class samples match these filters.")
        return
    figure = go.Figure()
    for wait_class in sorted(breakdown["wait_class"].unique()):
        series = breakdown[breakdown["wait_class"] == wait_class]
        figure.add_trace(
            go.Scatter(
                x=series["timestamp"],
                y=series["db_time_pct"],
                mode="lines",
                name=wait_class,
                stackgroup="db-time",
                line={"color": WAIT_COLORS.get(wait_class, "#94a3b8"), "width": 1},
                hovertemplate=(
                    "%{x|%b %d, %H:%M} UTC<br>"
                    f"{wait_class}: %{{y:.1f}}% of DB time<extra></extra>"
                ),
            )
        )
    _add_change_markers(
        figure, changes, start_day, end_day, selected_event_ids
    )
    figure.update_layout(
        **CHART_LAYOUT,
        title="Wait-class share of DB time over time",
        height=430,
        hovermode="x unified",
        legend_title_text="Wait class",
    )
    figure.update_xaxes(title="Time (UTC)")
    figure.update_yaxes(
        title="DB time by wait class (%)",
        range=[0, 100],
        ticksuffix="%",
        gridcolor="rgba(148,163,184,0.14)",
    )
    apply_time_axis(figure, start_day, end_day)
    st.caption(
        "Shares use execution-weighted hourly averages; time not assigned to the top wait class is attributed to CPU."
    )
    st.plotly_chart(figure, width="stretch")


def _plan_regression_table(db, baseline_db, changes, start_day, end_day, selected_event_ids):
    plan_data = db
    if selected_event_ids and baseline_db is not None and not baseline_db.empty:
        plan_data = pd.concat([db, baseline_db], ignore_index=True).drop_duplicates()
    regressions = detect_plan_regressions(plan_data, start_day, end_day)
    if selected_event_ids:
        relevant_times = changes[
            changes["change_id"].isin(selected_event_ids)
        ]["timestamp"]
        if not relevant_times.empty:
            lower = relevant_times.min() - pd.Timedelta(hours=24)
            upper = relevant_times.max() + pd.Timedelta(hours=24)
            regressions = regressions[
                regressions["change_time"].between(lower, upper, inclusive="both")
            ]
    if regressions.empty:
        st.info(
            "No SQL plan changes with elapsed-time regressions match these filters."
        )
        return
    display = regressions.rename(
        columns={
            "sql_id": "SQL ID",
            "old_plan": "Old plan",
            "new_plan": "New plan",
            "change_time": "Change time (UTC)",
            "elapsed_before_ms": "Elapsed before (ms)",
            "elapsed_after_ms": "Elapsed after (ms)",
            "regression_factor": "Regression factor",
        }
    ).copy()
    display["Change time (UTC)"] = display["Change time (UTC)"].dt.strftime(
        "%Y-%m-%d %H:%M"
    )
    display["Elapsed before (ms)"] = display["Elapsed before (ms)"].map(
        lambda value: f"{value:,.1f}"
    )
    display["Elapsed after (ms)"] = display["Elapsed after (ms)"].map(
        lambda value: f"{value:,.1f}"
    )
    display["Regression factor"] = display["Regression factor"].map(
        lambda value: f"{value:.1f}×"
    )
    st.dataframe(display, hide_index=True, width="stretch")


def render_database_health(
    db,
    changes,
    start_day,
    end_day,
    selected_event_ids=None,
    baseline_db=None,
):
    selected_event_ids = selected_event_ids or []
    if db.empty:
        st.info(
            "No database metrics match these filters. Adjust the sidebar filters to see results."
        )
        return

    st.subheader("DB time by connection user")
    _db_time_chart(db)

    st.subheader("Top SQL by elapsed time")
    _top_sql_table(db)

    st.subheader("Elapsed-time trend by SQL ID")
    _elapsed_trend(db, changes, start_day, end_day, selected_event_ids)

    st.subheader("Wait class breakdown")
    _wait_class_trend(db, changes, start_day, end_day, selected_event_ids)

    st.subheader("Plan change detection")
    _plan_regression_table(
        db,
        baseline_db,
        changes,
        start_day,
        end_day,
        selected_event_ids,
    )
