"""Run every question in order and write the results to outputs/.

Usage: python run.py path/to/BPI_Challenge_2019.csv
"""
import json
import sys
from pathlib import Path

from src import load, analysis, value, mining

csv_path = Path(sys.argv[1] if len(sys.argv) > 1 else "data/BPI_Challenge_2019.csv")
out = Path("outputs")
out.mkdir(exist_ok=True)

raw = load.load(csv_path, cache_path=csv_path.with_suffix(".pkl"))
df, cleaning = load.clean(raw)
print("Cleaning:", cleaning)

cases = analysis.case_table(df)

mix = analysis.q1_mix(cases)
mix.to_csv(out / "q1_category_mix.csv")
print("\nQ1 category mix\n", mix)

variants, n_variants = analysis.q2_variants(df)
variants.to_csv(out / "q2_top_variants.csv")
print(f"\nQ2 distinct paths: {n_variants:,}; top 10 cover {variants['cumulative_share'].iloc[-1]:.1%}")

rework_cat = analysis.q3_rework(cases)
rework_area = analysis.q3_rework(cases, by="spend_area")
rework_cat.to_csv(out / "q3_rework_by_category.csv")
rework_area.to_csv(out / "q3_rework_by_spend_area.csv")
analysis.rework_events(df).to_csv(out / "q3_rework_events.csv")
print("\nQ3 rework by category\n", rework_cat)

paid = analysis.q4_paid_before_goods(cases)
paid.to_csv(out / "q4_paid_before_goods.csv")
flagged = analysis.flagged_items(cases)
flagged[["flag", "item_category", "spend_area", "po_value_eur", "t_first_gr", "t_first_clear",
         "n_gr", "n_cancel_gr", "n_gr_at_clear", "n_cancel_gr_at_clear"]].to_csv(
    out / "q4_review_list.csv")
print("\nQ4 paid items by goods-receipt group\n", paid)
for cat in analysis.THREE_WAY:
    print(f"invoice recorded before goods, {cat}: {analysis.invoice_before_goods_rate(cases, cat):.1%}")

cyc, blk = analysis.q5_cycle_time(cases)
cyc.to_csv(out / "q5_cycle_days_by_category.csv")
blk.to_csv(out / "q5_cycle_days_by_payment_block.csv")
print("\nQ5 cycle days\n", cyc, "\n", blk)

touches = value.manual_touches(df)
vr = value.value_range(touches)
vr.to_csv(out / "value_range.csv")
print("\nValue range\n", vr)

# Q6 and Q7 use PM4Py on the main category.
main_log = mining.to_pm4py(df[df["item_category"] == mining.MAIN])
edges = mining.process_map(main_log, path=str(out / "q6_process_map.png"))
edges.to_csv(out / "q6_top_handoffs.csv")
net, im, fm = mining.standard_model(main_log)
mining.pm4py.save_vis_petri_net(net, im, fm, str(out / "q7_standard_model.png"))
conf, fit = mining.conformance(main_log, net, im, fm)
mining.off_model_steps(main_log, net, fit).to_csv(out / "q7_off_model_steps.csv")
(out / "q7_conformance.json").write_text(json.dumps(conf, indent=2))
print("\nQ7 conformance\n", conf)

(out / "cleaning.json").write_text(json.dumps(cleaning, indent=2))
