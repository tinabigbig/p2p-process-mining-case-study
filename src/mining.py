"""Process mining views with PM4Py, on top of the pandas analysis.

Q6  What does the process map of the main category look like?
Q7  How many items follow the standard process? The standard process is the model
    discovered from the 10 most common paths; every item is then replayed against it.
"""
import pandas as pd
import pm4py

MAIN = "3-way match, invoice before GR"


def to_pm4py(df):
    """PM4Py expects case, activity and timestamp under its own column names."""
    return pm4py.format_dataframe(df, case_id="case_id", activity_key="activity",
                                  timestamp_key="ts")


def process_map(log, top_variants=20, path=None):
    """Directly-follows map of the most common paths, with how often each step follows another."""
    top = pm4py.filter_variants_top_k(log, top_variants)
    dfg, start, end = pm4py.discover_dfg(top)
    if path:
        pm4py.save_vis_dfg(dfg, start, end, path, rankdir="TB")
    edges = (pd.Series(dfg).rename("times").rename_axis(["from", "to"])
             .sort_values(ascending=False).to_frame())
    return edges


def standard_model(log, top_variants=10):
    top = pm4py.filter_variants_top_k(log, top_variants)
    return pm4py.discover_petri_net_inductive(top)


def conformance(log, net, im, fm):
    """Token-based replay: an item fits if it can run through the standard model with no
    missing or leftover tokens."""
    diag = pm4py.conformance_diagnostics_token_based_replay(log, net, im, fm)
    fit = pd.Series([d["trace_is_fit"] for d in diag])
    fitness = pm4py.fitness_token_based_replay(log, net, im, fm)
    summary = {
        "cases": len(fit),
        "fitting_cases": int(fit.sum()),
        "fitting_share": float(fit.mean()),
        "log_fitness": float(fitness["log_fitness"]),
    }
    return summary, fit


def off_model_steps(log, net, fit):
    """Which steps show up in the items that do not fit? Counted once per item."""
    in_model = {t.label for t in net.transitions if t.label}
    case_ids = log["case:concept:name"].drop_duplicates().tolist()
    misfit = {c for c, ok in zip(case_ids, fit) if not ok}
    m = log[log["case:concept:name"].isin(misfit)]
    m = m[~m["concept:name"].isin(in_model)].drop_duplicates(["case:concept:name", "concept:name"])
    out = m["concept:name"].value_counts().rename("misfit_items").to_frame()
    out["share_of_misfit_items"] = out["misfit_items"] / len(misfit)
    return out
