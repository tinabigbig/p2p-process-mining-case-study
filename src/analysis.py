"""The questions, in order. Each function answers one and returns a small table.

Q1  How big is the process and which matching type does each item follow?
Q2  How many different paths do items take, and how much do the top paths cover?
Q3  How often is an item reworked (price, quantity, approval, deletion, cancellation)?
Q4  Are 3-way match items ever paid (invoice cleared) before the goods receipt, or
    with no goods receipt at all? 3-way match means PO, goods receipt and invoice
    should all agree before payment.
Q5  How long from creating the PO item to clearing the invoice, and how much do
    payment blocks add?
"""
import pandas as pd

REWORK = [
    "Change Price",
    "Change Quantity",
    "Change Delivery Indicator",
    "Delete Purchase Order Item",
    "Cancel Goods Receipt",
    "Cancel Invoice Receipt",
]
THREE_WAY = ["3-way match, invoice before GR", "3-way match, invoice after GR"]
# "Change Approval for Purchase Order" is left out of REWORK on purpose: in 2-way match
# items it is a routine approval step on almost every item, not a correction.


def receipt_counts_at_clearing(df, t_clear):
    """For each case, goods receipts and receipt cancellations: in the whole log, and up to
    the moment the invoice was first cleared. Payment is judged on what existed then."""
    gr = df[df["activity"].isin(["Record Goods Receipt", "Cancel Goods Receipt"])].copy()
    gr["t_clear"] = gr["case_id"].map(t_clear)
    # Tie rule: a timestamp shared with the clearing cannot prove which came first, so a
    # receipt only counts if it is strictly earlier, and a cancellation counts if it is at
    # or before the clearing. Both choices lean towards flagging. (No ties occur in BPI 2019.)
    is_receipt = gr["activity"] == "Record Goods Receipt"
    before = gr["ts"] < gr["t_clear"]
    at_or_before = gr["ts"] <= gr["t_clear"]
    gr["by_clearing"] = gr["t_clear"].notna() & ((is_receipt & before) | (~is_receipt & at_or_before))
    total = gr.pivot_table(index="case_id", columns="activity", values="event_id", aggfunc="size")
    upto = gr[gr["by_clearing"]].pivot_table(index="case_id", columns="activity",
                                             values="event_id", aggfunc="size")
    cols = ["Record Goods Receipt", "Cancel Goods Receipt"]
    total = total.reindex(columns=cols).fillna(0)
    upto = upto.reindex(columns=cols).fillna(0)
    total.columns = ["n_gr", "n_cancel_gr"]
    upto.columns = ["n_gr_at_clear", "n_cancel_gr_at_clear"]
    return total.join(upto, how="outer").fillna(0)


def case_table(df):
    """One row per case: category, spend area, value and the first time of key steps."""
    first = df.pivot_table(index="case_id", columns="activity", values="ts", aggfunc="min")
    keep = ["Create Purchase Order Item", "Record Goods Receipt",
            "Record Invoice Receipt", "Clear Invoice"]
    first = first.reindex(columns=keep)
    first.columns = ["t_create", "t_first_gr", "t_first_invoice", "t_first_clear"]
    counts = receipt_counts_at_clearing(df, first["t_first_clear"])
    attrs = df.groupby("case_id").agg(
        item_category=("item_category", "first"),
        spend_area=("spend_area", "first"),
        n_events=("event_id", "size"),
    )
    value = (df[df["activity"] == "Create Purchase Order Item"]
             .groupby("case_id")["net_worth_eur"].first().rename("po_value_eur"))
    acts = df.groupby("case_id")["activity"].agg(set)
    cases = attrs.join(first).join(counts).join(value)
    # Items with no receipt events at all are missing from counts: they have zero, not unknown.
    count_cols = ["n_gr", "n_cancel_gr", "n_gr_at_clear", "n_cancel_gr_at_clear"]
    cases[count_cols] = cases[count_cols].fillna(0)
    cases["is_rework"] = acts.apply(lambda s: bool(s & set(REWORK)))
    cases["has_payment_block"] = acts.apply(lambda s: "Remove Payment Block" in s)
    return cases


def q1_mix(cases):
    out = cases.groupby("item_category").agg(cases=("n_events", "size"),
                                             events=("n_events", "sum"))
    out["share_of_cases"] = out["cases"] / out["cases"].sum()
    return out.sort_values("cases", ascending=False)


def q2_variants(df, top=10):
    """A variant is the ordered list of activities in a case."""
    paths = df.groupby("case_id")["activity"].agg(" > ".join)
    counts = paths.value_counts()
    out = counts.head(top).rename("cases").to_frame()
    out["share_of_cases"] = out["cases"] / counts.sum()
    out["cumulative_share"] = out["share_of_cases"].cumsum()
    return out, len(counts)


def q3_rework(cases, by="item_category"):
    out = cases.groupby(by).agg(cases=("is_rework", "size"), rework_cases=("is_rework", "sum"))
    out["rework_rate"] = out["rework_cases"] / out["cases"]
    return out.sort_values("cases", ascending=False)


def rework_events(df):
    return df[df["activity"].isin(REWORK)]["activity"].value_counts().rename("events").to_frame()


def payment_flag(cases):
    """Sort every paid 3-way match item into one group, judged at its first invoice clearing.
    The groups do not overlap.

    paid_before_goods        no receipt yet when cleared; a receipt was posted later
    receipts_cancelled       receipts posted before clearing, but all of them were cancelled
                             before clearing too (counting events, so treat as a first screen)
    no_goods_trace           no goods receipt and no cancellation anywhere in the log
    receipt_missing_cancel   no goods receipt in the log, but a cancelled one is: the receipt
                             was most likely posted outside this extract (a data gap to check)
    ok                       at least one receipt still standing when the invoice was cleared
    """
    c = cases[cases["item_category"].isin(THREE_WAY) & cases["t_first_clear"].notna()].copy()
    valid_at_clear = (c["n_gr_at_clear"] - c["n_cancel_gr_at_clear"]) > 0
    c["flag"] = "ok"
    no_gr_ever = c["n_gr"] == 0
    c.loc[no_gr_ever & (c["n_cancel_gr"] == 0), "flag"] = "no_goods_trace"
    c.loc[no_gr_ever & (c["n_cancel_gr"] > 0), "flag"] = "receipt_missing_cancel"
    c.loc[~no_gr_ever & (c["n_gr_at_clear"] == 0), "flag"] = "paid_before_goods"
    c.loc[~no_gr_ever & (c["n_gr_at_clear"] > 0) & ~valid_at_clear, "flag"] = "receipts_cancelled"
    return c


def q4_paid_before_goods(cases):
    """Items and order value per group, by category."""
    c = payment_flag(cases)
    out = c.pivot_table(index="flag", columns="item_category", values="po_value_eur",
                        aggfunc=["size", "sum"], fill_value=0)
    out.columns = [f"{'items' if a == 'size' else 'po_value_eur'} | {b}" for a, b in out.columns]
    return out


def invoice_before_goods_rate(cases, category):
    c = cases[(cases["item_category"] == category)
              & cases["t_first_gr"].notna() & cases["t_first_invoice"].notna()]
    return (c["t_first_invoice"] < c["t_first_gr"]).mean()


def flagged_items(cases):
    """The review list, most serious group first, then largest value first."""
    order = ["paid_before_goods", "no_goods_trace", "receipts_cancelled", "receipt_missing_cancel"]
    c = payment_flag(cases)
    c = c[c["flag"] != "ok"].copy()
    c["flag"] = pd.Categorical(c["flag"], order, ordered=True)
    return c.sort_values(["flag", "po_value_eur"], ascending=[True, False])


def q5_cycle_time(cases):
    """Days from creating the PO item to the first invoice clearing, for cleared items."""
    c = cases[cases["t_create"].notna() & cases["t_first_clear"].notna()].copy()
    c["days"] = (c["t_first_clear"] - c["t_create"]).dt.total_seconds() / 86400
    c = c[c["days"] >= 0]
    by_cat = c.groupby("item_category")["days"].agg(
        cases="size", median="median", p90=lambda s: s.quantile(0.9))
    by_block = c.groupby("has_payment_block")["days"].agg(cases="size", median="median")
    return by_cat.sort_values("cases", ascending=False), by_block
