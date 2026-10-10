"""Shared filtering for Overview metrics and comparison periods."""

from __future__ import annotations

from datetime import date

import pandas as pd

PERIODIC_DATASETS = ("api", "kafka", "db")


def utc_day_bounds(start_day: date, end_day: date) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Return a UTC-inclusive start and exclusive end for selected calendar days."""
    start = pd.Timestamp(start_day).tz_localize("UTC")
    end = (pd.Timestamp(end_day) + pd.Timedelta(days=1)).tz_localize("UTC")
    return start, end


def _event_window_mask(
    timestamps: pd.Series,
    events: pd.DataFrame,
    event_ids: list[str],
    focus: str,
) -> pd.Series:
    mask = pd.Series(False, index=timestamps.index)
    selected = events[events["change_id"].isin(event_ids)]
    for event_time in selected["timestamp"]:
        if focus == "after":
            mask |= (timestamps >= event_time) & (
                timestamps < event_time + pd.Timedelta(hours=24)
            )
        else:
            mask |= (timestamps >= event_time - pd.Timedelta(hours=24)) & (
                timestamps < event_time
            )
    return mask


def _filter_dimensions(
    datasets: dict[str, pd.DataFrame],
    service_names: list[str],
    caller_types: list[str],
    topics: list[str],
    db_instances: list[str],
) -> dict[str, pd.DataFrame]:
    api = datasets["api"]
    kafka = datasets["kafka"]
    db = datasets["db"]

    if service_names:
        api = api[api["service"].isin(service_names)]
        kafka_owners = kafka["consumer_group"].str.replace(
            r"-consumer$", "", regex=True
        )
        kafka = kafka[kafka_owners.isin(service_names)]
        db_services = (
            db["db_user"]
            .str.extract(r"^SVC_([^_]+)_(?:API|CONSUMER)$")[0]
            .str.lower()
        )
        db = db[db_services.isin(service_names)]

    if caller_types:
        caller_suffixes = [
            "API" if caller == "API" else "CONSUMER"
            for caller in caller_types
        ]
        db = db[db["db_user"].str.rsplit("_", n=1).str[-1].isin(caller_suffixes)]

    if topics:
        kafka = kafka[kafka["topic"].isin(topics)]
    if db_instances:
        db = db[db["db_instance"].isin(db_instances)]

    return {"api": api, "kafka": kafka, "db": db}


def filter_datasets(
    datasets: dict[str, pd.DataFrame],
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
    *,
    service_names: list[str],
    caller_types: list[str],
    topics: list[str],
    db_instances: list[str],
    selected_event_ids: list[str],
    event_focus: str | None = None,
) -> dict[str, pd.DataFrame]:
    """Apply time, event, service, caller, topic, and instance filters."""
    filtered = {}
    for key in PERIODIC_DATASETS:
        frame = datasets[key]
        mask = pd.Series(True, index=frame.index)
        if start is not None:
            mask &= frame["timestamp"] >= start
        if end is not None:
            mask &= frame["timestamp"] < end
        if selected_event_ids and event_focus:
            mask &= _event_window_mask(
                frame["timestamp"],
                datasets["changes"],
                selected_event_ids,
                event_focus,
            )
        filtered[key] = frame[mask]

    dimension_filtered = _filter_dimensions(
        filtered,
        service_names,
        caller_types,
        topics,
        db_instances,
    )
    return {
        **dimension_filtered,
        "changes": datasets["changes"],
    }


def current_and_baseline(
    datasets: dict[str, pd.DataFrame],
    start_day: date,
    end_day: date,
    selections: dict,
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    """Build the selected range and its prior-period (or pre-change) baseline."""
    start, end = utc_day_bounds(start_day, end_day)
    common = {
        "service_names": selections["services"],
        "caller_types": selections["caller_types"],
        "topics": selections["topics"],
        "db_instances": selections["db_instances"],
        "selected_event_ids": selections["event_ids"],
    }

    if selections["event_ids"]:
        current = filter_datasets(
            datasets, start, end, **common, event_focus="after"
        )
        baseline = filter_datasets(
            datasets, None, None, **common, event_focus="before"
        )
    else:
        duration = end - start
        current = filter_datasets(datasets, start, end, **common)
        baseline = filter_datasets(
            datasets, start - duration, start, **common
        )
    return current, baseline
