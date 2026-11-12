"""Small hand-built event log. Every expected number below can be checked by eye."""
import os

import pandas as pd
import pytest

from src import load, analysis, value

BEFORE = "3-way match, invoice before GR"
AFTER = "3-way match, invoice after GR"


def ev(eid, case, cat, act, day, worth=100.0, area="Sales"):
    return {"event_id": str(eid), "case_id": case, "item_category": cat, "spend_area": area,
            "vendor": "v1", "activity": act, "net_worth_eur": worth,
            "ts": pd.Timestamp("2018-01-01") + pd.Timedelta(days=day)}


@pytest.fixture
def log():
    rows = [
        # A: clean path, invoice after goods, paid on day 30
        ev(1, "A", BEFORE, "Create Purchase Order Item", 0),
        ev(2, "A", BEFORE, "Record Goods Receipt", 5),
        ev(3, "A", BEFORE, "Record Invoice Receipt", 6),
        ev(4, "A", BEFORE, "Clear Invoice", 30),
        # B: price change (rework), invoice first, paid BEFORE goods
        ev(5, "B", BEFORE, "Create Purchase Order Item", 0, worth=500.0),
        ev(6, "B", BEFORE, "Change Price", 1, worth=500.0),
        ev(7, "B", BEFORE, "Record Invoice Receipt", 2, worth=500.0),
        ev(8, "B", BEFORE, "Clear Invoice", 10, worth=500.0),
        ev(9, "B", BEFORE, "Record Goods Receipt", 12, worth=500.0),
        # C: paid with NO goods receipt, payment block removed
        ev(10, "C", AFTER, "Create Purchase Order Item", 0, worth=50.0),
        ev(11, "C", AFTER, "Record Invoice Receipt", 3, worth=50.0),
        ev(12, "C", AFTER, "Remove Payment Block", 20, worth=50.0),
        ev(13, "C", AFTER, "Clear Invoice", 40, worth=50.0),
        # D: bad 1948 date, whole case should be dropped
        ev(14, "D", BEFORE, "Create Purchase Order Item", 0),
        ev(15, "D", BEFORE, "Vendor creates invoice", -25550),
    ]
    rows.append(dict(rows[0]))  # exact duplicate of event 1
    return pd.DataFrame(rows)


@pytest.fixture
def clean(log):
    df, report = load.clean(log)
    return df, report


def test_clean_drops_duplicates_and_bad_date_cases(clean):
    df, report = clean
    assert report["events_in"] == 16
    assert report["cases_dropped_bad_dates"] == 1
    assert report["cases_out"] == 3
    assert df["event_id"].is_unique


def test_events_sorted_by_time_within_case(clean):
    df, _ = clean
    b = df[df["case_id"] == "B"]["activity"].tolist()
    assert b == ["Create Purchase Order Item", "Change Price", "Record Invoice Receipt",
                 "Clear Invoice", "Record Goods Receipt"]


def test_variants_are_ordered_paths(clean):
    df, _ = clean
    top, n = analysis.q2_variants(df)
    assert n == 3
    assert top["cases"].sum() == 3
    assert top["cumulative_share"].iloc[-1] == pytest.approx(1.0)


def test_rework_flag(clean):
    df, _ = clean
    cases = analysis.case_table(df)
    assert cases.loc["B", "is_rework"]
    assert not cases.loc["A", "is_rework"]
    assert not cases.loc["C", "is_rework"]  # removing a payment block is not rework


def test_payment_groups(clean):
    df, _ = clean
    cases = analysis.case_table(df)
    flags = analysis.payment_flag(cases)["flag"]
    assert flags["A"] == "ok"
    assert flags["B"] == "paid_before_goods"
    assert flags["C"] == "no_goods_trace"
    assert list(analysis.flagged_items(cases).index) == ["B", "C"]


def test_cancelled_receipt_groups_judged_at_clearing():
    base = pd.Timestamp("2018-01-01")

    def row(gr, cgr, gr_at, cgr_at):
        return {"item_category": BEFORE, "t_first_clear": base + pd.Timedelta(days=20),
                "t_first_gr": base + pd.Timedelta(days=5) if gr else pd.NaT,
                "n_gr": gr, "n_cancel_gr": cgr, "n_gr_at_clear": gr_at,
                "n_cancel_gr_at_clear": cgr_at, "po_value_eur": 10.0}
    cases = pd.DataFrame([
        row(0, 1, 0, 1),   # X: cancellation but no receipt in the log
        row(1, 1, 1, 1),   # Y: receipt and its cancellation both before clearing
        row(1, 1, 1, 0),   # Z: receipt cancelled only AFTER clearing, so fine at the time
        row(2, 1, 2, 1),   # W: two receipts, one cancelled, one still standing
    ], index=["X", "Y", "Z", "W"])
    flags = analysis.payment_flag(cases)["flag"]
    assert flags["X"] == "receipt_missing_cancel"
    assert flags["Y"] == "receipts_cancelled"
    assert flags["Z"] == "ok"
    assert flags["W"] == "ok"


def test_counts_at_clearing_use_event_time(clean):
    df, _ = clean
    cases = analysis.case_table(df)
    # B: goods receipt on day 12 comes after clearing on day 10
    assert cases.loc["B", "n_gr"] == 1
    assert cases.loc["B", "n_gr_at_clear"] == 0


def test_same_timestamp_tie_rule():
    t = pd.Timestamp("2018-03-01 23:59")
    rows = [
        ev(1, "T", BEFORE, "Create Purchase Order Item", 0),
        {**ev(2, "T", BEFORE, "Record Goods Receipt", 0), "ts": t},
        {**ev(3, "T", BEFORE, "Clear Invoice", 0), "ts": t},
        ev(4, "U", BEFORE, "Create Purchase Order Item", 0),
        {**ev(5, "U", BEFORE, "Record Goods Receipt", 0), "ts": t - pd.Timedelta(days=1)},
        {**ev(6, "U", BEFORE, "Cancel Goods Receipt", 0), "ts": t},
        {**ev(7, "U", BEFORE, "Clear Invoice", 0), "ts": t},
    ]
    df, _ = load.clean(pd.DataFrame(rows))
    flags = analysis.payment_flag(analysis.case_table(df))["flag"]
    assert flags["T"] == "paid_before_goods"     # same-time receipt does not count as earlier
    assert flags["U"] == "receipts_cancelled"    # same-time cancellation does count


def test_invoice_before_goods_rate(clean):
    df, _ = clean
    rate = analysis.invoice_before_goods_rate(analysis.case_table(df), BEFORE)
    # A: goods day 5, invoice day 6 (after). B: invoice day 2, goods day 12 (before).
    assert rate == pytest.approx(0.5)


def test_cycle_time_and_payment_block(clean):
    df, _ = clean
    by_cat, by_block = analysis.q5_cycle_time(analysis.case_table(df))
    assert by_cat.loc[AFTER, "median"] == pytest.approx(40.0)
    assert by_block.loc[True, "median"] == pytest.approx(40.0)
    assert by_block.loc[False, "median"] == pytest.approx(20.0)  # A=30, B=10


def test_value_range_arithmetic():
    vr = value.value_range(600)
    # base: 600 touches * 10 min = 100 h; 40% avoidable = 40 h; * 60/h = 2,400
    assert vr.loc["base", "total_hours"] == pytest.approx(100.0)
    assert vr.loc["base", "avoidable_cost_eur"] == pytest.approx(2400.0)
    assert vr.loc["low", "avoidable_cost_eur"] < vr.loc["base", "avoidable_cost_eur"] < vr.loc["high", "avoidable_cost_eur"]


def test_touch_count_includes_blocks_not_approvals(clean):
    df, _ = clean
    assert value.manual_touches(df) == 2  # Change Price + Remove Payment Block


def test_mining_map_and_conformance(clean):
    # Q6 and Q7 need PM4Py (pip install -r requirements.txt). Locally the test is skipped
    # without it; on GitHub Actions (CI is set) a missing PM4Py fails the run instead.
    if not os.environ.get("CI"):
        pytest.importorskip("pm4py")
    from src import mining
    df, _ = clean
    log = mining.to_pm4py(df)
    edges = mining.process_map(log, top_variants=3)
    assert edges.loc[("Create Purchase Order Item", "Record Goods Receipt"), "times"] == 1
    net, im, fm = mining.standard_model(log, top_variants=3)
    conf, fit = mining.conformance(log, net, im, fm)
    assert conf["cases"] == 3
    assert conf["fitting_cases"] == 3  # the model is learned from all three paths
