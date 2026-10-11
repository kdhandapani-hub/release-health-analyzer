"""Release Health Analyzer — Streamlit entry point."""

from datetime import date

import pandas as pd
import streamlit as st

from analysis.filters import current_and_baseline
from data.loader import load_datasets
from views.api_test_results import render_api_test_results
from views.database_health import render_database_health
from views.event_stream_health import render_event_stream_health
from views.infrastructure_health import render_infrastructure_health
from views.overview import render_overview
from views.root_cause_correlation import render_root_cause_correlation


def _all_hint(selected):
    if not selected:
        st.caption("All")


st.set_page_config(
    page_title="Release Health Analyzer",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      .stApp { background: #0b1220; color: #e6edf7; }
      [data-testid="stSidebar"] { background: #101a2b; }
      [data-testid="stMarkdownContainer"],
      [data-testid="stWidgetLabel"] p,
      [data-testid="stCaptionContainer"] p { color: #d9e2f1; }
      [data-testid="stMetricLabel"] p { color: #b7c5d8 !important; }
      [data-testid="stMetricValue"] div { color: #f8fafc !important; }
      [data-testid="stMetricDelta"] { font-weight: 650; }
      [data-testid="stMetric"] {
        background: rgba(23, 36, 56, 0.72);
        border: 1px solid rgba(148, 163, 184, 0.16);
        border-radius: 12px;
        padding: 12px 14px;
      }
      .health-badge {
        display: inline-block;
        float: right;
        padding: 5px 10px;
        border-radius: 999px;
        font-size: 0.78rem;
        font-weight: 700;
        letter-spacing: .02em;
      }
      .health-healthy { color: #86efac; background: rgba(34,197,94,.13); }
      .health-warning { color: #fcd34d; background: rgba(245,158,11,.15); }
      .health-critical { color: #fda4af; background: rgba(244,63,94,.15); }
      .health-unavailable { color: #cbd5e1; background: rgba(148,163,184,.13); }
      [data-baseweb="tag"] {
        background: #183450 !important;
        color: #e7f2ff !important;
        border: 1px solid #315b7e !important;
      }
      div[data-testid="stVerticalBlockBorderWrapper"] {
        border-color: rgba(148, 163, 184, 0.15);
        border-radius: 16px;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Release Health Analyzer")
st.caption(
    "Connect change events to API performance, event-stream health, and database behavior."
)

try:
    datasets = load_datasets()
except (FileNotFoundError, OSError, pd.errors.ParserError) as error:
    st.error(f"Unable to load the generated datasets: {error}")
    st.stop()

all_timestamps = pd.concat(
    [datasets[key]["timestamp"] for key in ("api", "kafka", "db")],
    ignore_index=True,
)
minimum_day = all_timestamps.min().date()
maximum_day = all_timestamps.max().date()
default_date_range = (minimum_day, maximum_day)
requested_day = st.query_params.get("day")
if requested_day:
    try:
        preview_day = date.fromisoformat(requested_day)
    except ValueError:
        preview_day = None
    if preview_day is not None and minimum_day <= preview_day <= maximum_day:
        default_date_range = (preview_day, preview_day)

with st.sidebar:
    st.header("Filters")
    selected_dates = st.date_input(
        "Date range",
        value=default_date_range,
        min_value=minimum_day,
        max_value=maximum_day,
        help="Defaults to the full date range available in the generated data.",
    )
    if isinstance(selected_dates, (tuple, list)):
        if len(selected_dates) == 2:
            start_day, end_day = selected_dates
        elif len(selected_dates) == 1:
            start_day = end_day = selected_dates[0]
        else:
            start_day, end_day = minimum_day, maximum_day
    else:
        start_day = end_day = selected_dates

    service_options = sorted(datasets["api"]["service"].dropna().unique().tolist())
    selected_services = st.multiselect(
        "Service",
        service_options,
        default=[],
        help="Applies to API services, consumer owners, and database connection users. Leave empty for all.",
    )
    _all_hint(selected_services)
    selected_callers = st.multiselect(
        "Caller type",
        ["API", "Consumer"],
        default=[],
        help="Limits database connection users by API or consumer caller. Leave empty for all.",
    )
    _all_hint(selected_callers)

    event_ids = datasets["changes"]["change_id"].tolist()
    event_lookup = datasets["changes"].set_index("change_id")
    selected_events = st.multiselect(
        "Change event",
        event_ids,
        default=[],
        format_func=lambda change_id: (
            f"{change_id} · {event_lookup.loc[change_id, 'change_type']} · "
            f"{event_lookup.loc[change_id, 'timestamp'].strftime('%b %d %H:%M')} UTC"
        ),
        help="Selecting an event compares its following 24 hours with the preceding 24 hours. Leave empty for all.",
    )
    _all_hint(selected_events)
    topic_options = sorted(datasets["kafka"]["topic"].dropna().unique().tolist())
    selected_topics = st.multiselect(
        "Topic",
        topic_options,
        default=[],
        help="Leave empty for all topics.",
    )
    _all_hint(selected_topics)
    instance_options = sorted(
        datasets["db"]["db_instance"].dropna().unique().tolist()
    )
    selected_instances = st.multiselect(
        "DB instance",
        instance_options,
        default=[],
        help="Leave empty for all database instances.",
    )
    _all_hint(selected_instances)
    if "infra" in datasets:
        infra_tier_options = sorted(
            datasets["infra"]["tier"].dropna().unique().tolist()
        )
        selected_infra_tiers = st.multiselect(
            "Infra tier",
            infra_tier_options,
            default=[],
            help="Leave empty for all infrastructure tiers.",
        )
        _all_hint(selected_infra_tiers)
    else:
        selected_infra_tiers = []

selections = {
    "services": selected_services,
    "caller_types": selected_callers,
    "topics": selected_topics,
    "db_instances": selected_instances,
    "event_ids": selected_events,
    "infra_tiers": selected_infra_tiers,
}
current, baseline = current_and_baseline(
    datasets,
    start_day,
    end_day,
    selections,
)

tab_names = [
    "Overview",
    "API Test Results",
    "Event Stream Health",
    "Database Health",
]
if "infra" in datasets:
    tab_names.append("Infrastructure Health")
tab_names.extend(["Root Cause Correlation", "AI Insights"])
requested_view = st.query_params.get("view", "Overview")
default_view = requested_view if requested_view in tab_names else "Overview"
tabs = st.tabs(tab_names, default=default_view)

with tabs[0]:
    render_overview(current, baseline, start_day, end_day)

with tabs[1]:
    render_api_test_results(current["api"], start_day, end_day)

with tabs[2]:
    render_event_stream_health(current["kafka"], start_day, end_day)

with tabs[3]:
    render_database_health(
        current["db"],
        datasets["changes"],
        start_day,
        end_day,
        selected_event_ids=selected_events,
        baseline_db=baseline["db"] if selected_events else None,
    )

if "infra" in datasets:
    with tabs[4]:
        render_infrastructure_health(
            current["infra"],
            start_day,
            end_day,
        )

root_cause_tab_index = 5 if "infra" in datasets else 4
with tabs[root_cause_tab_index]:
    render_root_cause_correlation(
        current["api"],
        current["kafka"],
        current["db"],
        datasets["changes"],
        start_day,
        end_day,
        selected_event_ids=selected_events,
        infra=current.get("infra"),
    )

with tabs[root_cause_tab_index + 1]:
    st.info("Coming soon")
