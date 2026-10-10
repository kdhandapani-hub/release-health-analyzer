"""Date-range-aware formatting for chart time axes."""

from datetime import date

import pandas as pd


HOUR_MS = 60 * 60 * 1000
DAY_MS = 24 * HOUR_MS


def apply_time_axis(figure, start_day: date, end_day: date):
    """Use horizontal 6-hour ticks for one day and daily ticks for longer ranges."""
    day_count = (end_day - start_day).days + 1
    tick0 = pd.Timestamp(start_day).tz_localize("UTC")
    if day_count == 1:
        tick_interval = 6 * HOUR_MS
        tick_format = "%H:%M"
    else:
        tick_interval = DAY_MS
        tick_format = "%b %-d"

    figure.update_xaxes(
        title="Time (UTC)",
        type="date",
        tickmode="linear",
        tick0=tick0,
        dtick=tick_interval,
        tickformat=tick_format,
        tickangle=0,
        automargin=True,
        showgrid=False,
    )
    return figure
