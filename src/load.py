"""Load the BPI Challenge 2019 event log and reduce it to the columns we use.

One row = one event. A case = one purchase order item (case concept:name).
"""
from pathlib import Path
import pandas as pd

COLUMNS = {
    "eventID ": "event_id",
    "case concept:name": "case_id",
    "case Item Category": "item_category",
    "case Spend area text": "spend_area",
    "case Vendor": "vendor",
    "event concept:name": "activity",
    "event Cumulative net worth (EUR)": "net_worth_eur",
    "event time:timestamp": "ts",
}

# Events dated outside this window are data-entry noise (the log has dates back to 1948).
WINDOW_START = pd.Timestamp("2017-01-01")
WINDOW_END = pd.Timestamp("2019-12-31 23:59:59")


def read_raw(csv_path):
    df = pd.read_csv(csv_path, usecols=list(COLUMNS), encoding="latin-1", dtype=str)
    df = df.rename(columns=COLUMNS)
    df["ts"] = pd.to_datetime(df["ts"], format="%d-%m-%Y %H:%M:%S.%f")
    df["net_worth_eur"] = pd.to_numeric(df["net_worth_eur"])
    return df


def clean(df):
    """Drop duplicate events, then drop whole cases that have any event outside the window.

    Returns the cleaned log and a small dict saying what was removed.
    """
    before_events, before_cases = len(df), df["case_id"].nunique()
    df = df.drop_duplicates("event_id")
    outside = (df["ts"] < WINDOW_START) | (df["ts"] > WINDOW_END)
    bad_cases = set(df.loc[outside, "case_id"])
    df = df[~df["case_id"].isin(bad_cases)].copy()
    # Order events inside each case: time first, event id breaks ties.
    df["event_id_num"] = df["event_id"].astype("int64")
    df = df.sort_values(["case_id", "ts", "event_id_num"]).reset_index(drop=True)
    report = {
        "events_in": before_events,
        "cases_in": before_cases,
        "cases_dropped_bad_dates": len(bad_cases),
        "events_out": len(df),
        "cases_out": df["case_id"].nunique(),
    }
    return df, report


def load(csv_path, cache_path=None):
    """Read the CSV once and keep a pickle next to it so reruns are fast."""
    if cache_path and Path(cache_path).exists():
        return pd.read_pickle(cache_path)
    df = read_raw(csv_path)
    if cache_path:
        df.to_pickle(cache_path)
    return df
