"""Turn manual touches into a range of hours and dollars.

Every figure here rests on assumptions, so each one is shown low, base and high.
The touch counts come from the data; minutes per touch and hourly cost do not.
"""
import pandas as pd

TOUCHES = [
    "Change Price", "Change Quantity",
    "Change Delivery Indicator", "Delete Purchase Order Item",
    "Cancel Goods Receipt", "Cancel Invoice Receipt", "Remove Payment Block",
]
SCENARIOS = {
    # minutes of someone's time per touch, loaded cost per hour (EUR, same currency as the log), share avoidable
    "low":  {"minutes": 5,  "cost_per_hour": 45, "avoidable": 0.25},
    "base": {"minutes": 10, "cost_per_hour": 60, "avoidable": 0.40},
    "high": {"minutes": 15, "cost_per_hour": 75, "avoidable": 0.55},
}


def manual_touches(df):
    return int(df["activity"].isin(TOUCHES).sum())


def value_range(touches):
    rows = []
    for name, s in SCENARIOS.items():
        hours = touches * s["minutes"] / 60
        avoidable_hours = hours * s["avoidable"]
        rows.append({
            "scenario": name,
            "touches": touches,
            "total_hours": hours,
            "avoidable_hours": avoidable_hours,
            "avoidable_cost_eur": avoidable_hours * s["cost_per_hour"],
        })
    return pd.DataFrame(rows).set_index("scenario")
