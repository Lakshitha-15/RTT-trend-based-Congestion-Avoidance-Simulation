#!/usr/bin/env python3
"""
analyze_sensitivity.py -- how strongly do the results depend on each algorithm parameter?

  python3 analysis/analyze_sensitivity.py results/exp_sens [--warmup 10]

Input: the 'sensitivity' suite of run_experiments.py (one scenario; baseline, default proposed,
and proposed with ONE parameter changed at a time). Output (in <root>/analysis/):
  sensitivity_table.csv   mean/std per configuration
  fig5_sensitivity.png    one row per parameter, one column per metric; dashed = baseline mean
"""
import argparse
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common_metrics import collect_runs  # noqa: E402

COLS = [("rtt_mean_ms", "mean RTT [ms]"), ("rtt_p95_ms", "p95 RTT [ms]"),
        ("goodput_mbps", "goodput [Mbit/s]"), ("loss_events_window", "loss events (steady state)"),
        ("fairness_jain", "Jain fairness"), ("frac_early", "time in EARLY_CONGESTION")]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root")
    ap.add_argument("--warmup", type=float, default=10.0)
    ap.add_argument("--recompute", action="store_true")
    a = ap.parse_args()

    df = collect_runs(a.root, a.warmup, recompute=a.recompute)
    if df.empty:
        sys.exit("no runs found")
    out = os.path.join(a.root, "analysis")
    os.makedirs(out, exist_ok=True)

    metric_cols = [c for c, _ in COLS]
    agg = df.groupby("label")[metric_cols].agg(["mean", "std"])
    agg.columns = [f"{m}_{s}" for m, s in agg.columns]
    agg["runs"] = df.groupby("label").size()
    agg.to_csv(os.path.join(out, "sensitivity_table.csv"))

    base = agg.loc["baseline"] if "baseline" in agg.index else None
    default = agg.loc["default"] if "default" in agg.index else None

    params = sorted({l.split("=")[0] for l in df.label.unique() if "=" in l})
    fig, axes = plt.subplots(len(params), len(COLS), figsize=(3.6 * len(COLS), 2.6 * len(params)))
    for i, p in enumerate(params):
        labels = [l for l in agg.index if l.startswith(p + "=")]
        vals = [float(l.split("=")[1]) for l in labels]
        order = np.argsort(vals)
        labels = [labels[j] for j in order]
        vals = [vals[j] for j in order]
        for j, (c, title) in enumerate(COLS):
            ax = axes[i, j]
            ax.errorbar(vals, agg.loc[labels, c + "_mean"], yerr=agg.loc[labels, c + "_std"].fillna(0),
                        fmt="o-", capsize=3, color="#DD8452")
            if base is not None and c in ("rtt_mean_ms", "rtt_p95_ms", "goodput_mbps", "loss_events_window",
                                           "fairness_jain"):
                ax.axhline(base[c + "_mean"], ls="--", c="#4C72B0", lw=1, label="baseline")
            if default is not None:
                ax.axhline(default[c + "_mean"], ls=":", c="black", lw=1, label="default proposed")
            if i == 0:
                ax.set_title(title, fontsize=9)
            if j == 0:
                ax.set_ylabel(p, fontweight="bold")
            ax.grid(alpha=0.3)
    axes[0, 0].legend(fontsize=7)
    fig.suptitle("Parameter sensitivity (2 flows, queue 100; mean +- std over runs)")
    fig.tight_layout()
    fig.savefig(os.path.join(out, "fig5_sensitivity.png"), dpi=120)

    pd.set_option("display.width", 220)
    show = ["rtt_mean_ms_mean", "rtt_p95_ms_mean", "goodput_mbps_mean", "loss_events_window_mean",
            "fairness_jain_mean", "frac_early_mean", "runs"]
    print(agg[show].round(2).to_string())
    print(f"\nFiles written to {out}/")


if __name__ == "__main__":
    main()
