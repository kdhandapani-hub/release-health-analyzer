"""Cached loading for the generated release-health datasets."""

from pathlib import Path

import pandas as pd
import streamlit as st


DATA_DIR = Path(__file__).resolve().parent
CSV_FILES = {
    "api": "api_test_runs.csv",
    "kafka": "kafka_metrics.csv",
    "db": "db_metrics.csv",
    "changes": "change_events.csv",
}
OPTIONAL_CSV_FILES = {
    "infra": "infra_metrics.csv",
}


@st.cache_data(show_spinner=False)
def load_datasets() -> dict[str, pd.DataFrame]:
    """Load the core synthetic CSVs and normalize their timestamps to UTC."""
    missing = [name for name in CSV_FILES.values() if not (DATA_DIR / name).is_file()]
    if missing:
        raise FileNotFoundError(
            "Required data files are missing: "
            + ", ".join(missing)
            + ". Run `python data/generate_data.py` first."
        )

    datasets = {
        key: pd.read_csv(DATA_DIR / filename)
        for key, filename in CSV_FILES.items()
    }
    for key, filename in OPTIONAL_CSV_FILES.items():
        path = DATA_DIR / filename
        if path.is_file():
            datasets[key] = pd.read_csv(path)
    for frame in datasets.values():
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
    datasets["api"]["passed"] = (
        datasets["api"]["passed"].astype(str).str.lower().eq("true")
    )
    return datasets
