"""Helpers for keeping nearby vertical event labels readable."""

import pandas as pd


def event_label_yshifts(timestamps, gap_hours=8, step_px=22):
    """Stagger annotation baselines within clusters of nearby event markers."""
    shifts = []
    previous = None
    cluster_index = 0
    for value in timestamps:
        timestamp = pd.Timestamp(value)
        if previous is None or timestamp - previous > pd.Timedelta(hours=gap_hours):
            cluster_index = 0
        else:
            cluster_index += 1
        shifts.append(-step_px * cluster_index)
        previous = timestamp
    return shifts
