#!/usr/bin/env python3
"""
analyze_experiments.py -- compare baseline TCP (TcpNewReno) with the RTT-trend algorithm
(TcpRttTrend) over the 'main' experiment suite.

  python3 analysis/analyze_experiments.py results/exp_main [--warmup 10] [--example n1_q100 n2_q100]

Reads only CSV files written by the simulation. Writes into <root>/analysis/:
  metrics_summary.csv      mean/std per scenario and algorithm
  paired_differences.csv   proposed - baseline per scenario (paired by run number) + 95% CI
  fig1_metric_bars.png     grouped bars (mean +- std over runs)
  fig2_paired_diff.png     paired differences with 95% confidence intervals
  fig3_tradeoff.png        throughput vs delay per scenario (arrow = baseline -> proposed)
  fig4_timeseries_*.png    one example run, baseline vs proposed, with the detector's state

Nothing is assumed about which algorithm is better: the verdict column only says whether the
95% CI of the paired difference excludes zero and in which direction.
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
from common_metrics import collect_runs, paired_ci, read_csv, read_summary  # noqa: E402

# metric -> (label, lower_is_better)
METRICS = {
    "rtt_mean_ms": ("mean RTT [ms]", True),
    "rtt_median_ms": ("median RTT [ms]", True),
    "rtt_p95_ms": ("95th pct RTT [ms]", True),
    "qdelay_mean_ms": ("mean queueing delay [ms]", True),
    "qdelay_p95_ms": ("95th pct queueing delay [ms]", True),
    "rtt_slope_abs_mean": ("mean |RTT slope| [ms/s]", True),
    "goodput_mbps": ("goodput [Mbit/s]", False),
    "drops_total": ("packets dropped (whole run)", True),
    "drops_window": ("packets dropped (steady state)", True),
    "retx_total": ("retransmitted segments (whole run)", True),
    "loss_events_window": ("loss-recovery events (steady state)", True),
    "cwnd_mean_segs": ("mean cwnd [segments]", None),
    "queue_mean_pkts": ("mean queue [packets]", True),
    "fairness_jain": ("Jain fairness index", False),
}
ALGOS = ("baseline", "proposed")
COLORS = {"baseline": "#4C72B0", "proposed": "#DD8452"}


def scenario_sort_key(s):
    n, q = s.replace("n", "").split("_q")
    return (int(n), int(q))


def nice(s):
    n, q = s.replace("n", "").split("_q")
    return f"{n} flow{'s' if int(n) > 1 else ''}\nqueue {q}"


def summarize(df):
    rows = []
    for (sc, algo), g in df.groupby(["scenario", "label"]):
        r = {"scenario": sc, "algo": algo, "runs": len(g)}
        for m in METRICS:
            r[m + "_mean"] = g[m].mean()
            r[m + "_std"] = g[m].std(ddof=1) if len(g) > 1 else float("nan")
        rows.append(r)
    return pd.DataFrame(rows)


def paired_table(df):
    rows = []
    for sc in sorted(df.scenario.unique(), key=scenario_sort_key):
        b = df[(df.scenario == sc) & (df.label == "baseline")].set_index("run")
        p = df[(df.scenario == sc) & (df.label == "proposed")].set_index("run")
        common = b.index.intersection(p.index)
        for m, (lab, lower) in METRICS.items():
            d = (p.loc[common, m] - b.loc[common, m]).to_numpy()
            mean, lo, hi, n = paired_ci(d)
            base_mean = b.loc[common, m].mean()
            if not np.isfinite(lo) or (lo <= 0 <= hi):
                verdict = "no clear difference"
            elif lower is None:
                verdict = "changed (neutral metric)"
            else:
                better = (mean < 0) if lower else (mean > 0)
                verdict = "proposed better" if better else "proposed worse"
            rows.append({"scenario": sc, "metric": m, "baseline_mean": base_mean,
                         "proposed_mean": p.loc[common, m].mean(), "diff_mean": mean,
                         "ci95_lo": lo, "ci95_hi": hi,
                         "rel_change_pct": 100 * mean / base_mean if base_mean else float("nan"),
                         "n_pairs": n, "verdict": verdict})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ plots
def fig_bars(summ, scenarios, out):
    keys = ["rtt_mean_ms", "rtt_p95_ms", "goodput_mbps", "loss_events_window", "retx_total",
            "queue_mean_pkts"]
    fig, axes = plt.subplots(2, 3, figsize=(16, 8))
    x = np.arange(len(scenarios))
    for ax, k in zip(axes.ravel(), keys):
        for i, algo in enumerate(ALGOS):
            s = summ[summ.algo == algo].set_index("scenario").loc[scenarios]
            ax.bar(x + (i - 0.5) * 0.38, s[k + "_mean"], 0.38, yerr=s[k + "_std"].fillna(0),
                   capsize=2, label=algo, color=COLORS[algo])
        ax.set_xticks(x)
        ax.set_xticklabels([nice(s) for s in scenarios], fontsize=7)
        ax.set_title(METRICS[k][0])
        ax.grid(axis="y", alpha=0.3)
    axes[0, 0].legend()
    fig.suptitle("Baseline (TcpNewReno) vs proposed (TcpRttTrend): mean +- std over runs "
                 "(steady state unless stated)")
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)


def fig_paired(pt, scenarios, out):
    keys = ["rtt_mean_ms", "rtt_p95_ms", "goodput_mbps", "loss_events_window", "retx_total",
            "queue_mean_pkts"]
    fig, axes = plt.subplots(2, 3, figsize=(16, 8))
    x = np.arange(len(scenarios))
    for ax, k in zip(axes.ravel(), keys):
        t = pt[pt.metric == k].set_index("scenario").loc[scenarios]
        err = np.vstack([(t.diff_mean - t.ci95_lo).fillna(0), (t.ci95_hi - t.diff_mean).fillna(0)])
        ax.errorbar(x, t.diff_mean, yerr=err, fmt="o", capsize=4, color="black")
        ax.axhline(0, c="gray", lw=1)
        ax.set_xticks(x)
        ax.set_xticklabels([nice(s) for s in scenarios], fontsize=7)
        lower = METRICS[k][1]
        hint = "" if lower is None else (" (below 0 = proposed better)" if lower else " (above 0 = proposed better)")
        ax.set_title(f"{METRICS[k][0]}: proposed - baseline{hint}", fontsize=9)
        ax.grid(alpha=0.3)
    fig.suptitle("Paired differences (same run number) with 95% confidence intervals")
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)


def fig_tradeoff(summ, scenarios, out):
    fig, ax = plt.subplots(figsize=(8, 6))
    for sc in scenarios:
        b = summ[(summ.scenario == sc) & (summ.algo == "baseline")].iloc[0]
        p = summ[(summ.scenario == sc) & (summ.algo == "proposed")].iloc[0]
        ax.annotate("", xy=(p.rtt_p95_ms_mean, p.goodput_mbps_mean),
                    xytext=(b.rtt_p95_ms_mean, b.goodput_mbps_mean),
                    arrowprops=dict(arrowstyle="->", color="gray"))
        ax.scatter(b.rtt_p95_ms_mean, b.goodput_mbps_mean, c=COLORS["baseline"], s=40)
        ax.scatter(p.rtt_p95_ms_mean, p.goodput_mbps_mean, c=COLORS["proposed"], s=40)
        ax.text(p.rtt_p95_ms_mean, p.goodput_mbps_mean, " " + sc, fontsize=7)
    ax.scatter([], [], c=COLORS["baseline"], label="baseline")
    ax.scatter([], [], c=COLORS["proposed"], label="proposed")
    ax.set(xlabel="95th percentile RTT [ms]  (lower is better)", ylabel="goodput [Mbit/s]  (higher is better)",
           title="Delay / throughput trade-off per scenario (arrow: baseline -> proposed)")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)


def state_segments(trend):
    """(start, end, state) segments from rtt_trend.csv of one flow."""
    if trend.empty:
        return []
    t = trend.time_s.to_numpy()
    st = trend.state.to_numpy()
    segs, start = [], 0
    for i in range(1, len(t) + 1):
        if i == len(t) or st[i] != st[start]:
            segs.append((t[start], t[i] if i < len(t) else t[-1], st[start]))
            start = i
    return segs


def fig_timeseries(root, scenario, run, out):
    base = os.path.join(root, scenario, "baseline", f"run{run}")
    prop = os.path.join(root, scenario, "proposed", f"run{run}")
    if not (os.path.isdir(base) and os.path.isdir(prop)):
        print(f"[skip] time-series figure: {base} or {prop} missing")
        return
    seg = read_summary(base)["param.segmentSize"]
    s = read_summary(prop)
    fig, ax = plt.subplots(5, 1, figsize=(13, 13), sharex=True,
                           gridspec_kw={"height_ratios": [1.3, 1.1, 1.1, 1, 1.1]})
    for name, d, c in (("baseline", base, COLORS["baseline"]), ("proposed", prop, COLORS["proposed"])):
        rtt = read_csv(d, "rtt")
        rtt = rtt[rtt.flow == 0]
        ax[0].plot(rtt.time_s, rtt.rtt_ms, lw=0.7, c=c, label=name)
        cw = read_csv(d, "cwnd")
        cw = cw[cw.flow == 0]
        ax[1].step(cw.time_s, cw.cwnd_bytes / seg, where="post", lw=0.8, c=c, label=name)
        q = read_csv(d, "queue")
        ax[2].step(q.time_s, q.queue_packets, where="post", lw=0.5, c=c, label=name)
        dr = read_csv(d, "drops")
        if not dr.empty:
            ax[2].plot(dr.time_s, [s["param.queuePackets"]] * len(dr), "x", c=c, ms=4)
    for name, d in (("baseline", base), ("proposed", prop)):
        tp = read_csv(d, "throughput")
        for f, g in tp.groupby("flow"):
            ax[4].plot(g.time_s, g.goodput_mbps.rolling(10, min_periods=1).mean(), lw=1.1,
                       ls="-" if name == "proposed" else "--", c=COLORS[name], alpha=1.0 - 0.35 * f,
                       label=f"{name} flow {f}")
    trend = read_csv(prop, "rtt_trend")
    trend = trend[trend.flow == 0] if not trend.empty else trend
    for a, b, st in state_segments(trend):
        if st != "NORMAL":
            for k in range(2):
                ax[k].axvspan(a, b, color="orange" if st == "EARLY_CONGESTION" else "red", alpha=0.12, lw=0)
    ax[3].plot(trend.time_s, trend.slope_ms_per_s, c=COLORS["proposed"], lw=0.9, label="RTT slope (proposed, flow 0)")
    ax[3].axhline(s["param.slopeEnter"], c="red", ls="--", lw=0.8, label="enter threshold")
    ax[3].axhline(s["param.slopeExit"], c="green", ls="--", lw=0.8, label="exit threshold")
    ax[3].axhline(0, c="gray", lw=0.5)
    ax[3].set_ylim(-15, 25)
    ax[0].set(ylabel="RTT [ms] (flow 0)", title=f"{scenario}, run {run}   (orange = EARLY_CONGESTION, red = CONGESTED)")
    ax[1].set(ylabel="cwnd [segments] (flow 0)")
    ax[2].set(ylabel="bottleneck queue [packets]  (x = drop)")
    ax[3].set(ylabel="RTT slope [ms/s]")
    ax[4].set(ylabel="goodput per flow [Mbit/s]\n(1 s mean)", xlabel="time [s]")
    for a in ax:
        a.legend(fontsize=8, loc="upper right")
        a.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", help="experiment root, e.g. results/exp_main")
    ap.add_argument("--warmup", type=float, default=10.0, help="seconds excluded from steady-state metrics")
    ap.add_argument("--example", nargs="+", default=["n1_q100", "n2_q100"],
                    help="scenario(s) for the time-series figure(s)")
    ap.add_argument("--example-run", type=int, default=1)
    ap.add_argument("--recompute", action="store_true", help="ignore cached metrics_per_run.csv")
    a = ap.parse_args()

    df = collect_runs(a.root, a.warmup, recompute=a.recompute)
    df = df[df.label.isin(ALGOS)]
    if df.empty:
        sys.exit(f"No finished runs found under {a.root}")
    out = os.path.join(a.root, "analysis")
    os.makedirs(out, exist_ok=True)
    scenarios = sorted(df.scenario.unique(), key=scenario_sort_key)

    summ = summarize(df)
    pt = paired_table(df)
    summ.to_csv(os.path.join(out, "metrics_summary.csv"), index=False)
    pt.to_csv(os.path.join(out, "paired_differences.csv"), index=False)

    fig_bars(summ, scenarios, os.path.join(out, "fig1_metric_bars.png"))
    fig_paired(pt, scenarios, os.path.join(out, "fig2_paired_diff.png"))
    fig_tradeoff(summ, scenarios, os.path.join(out, "fig3_tradeoff.png"))
    for ex in a.example:
        fig_timeseries(a.root, ex, a.example_run,
                       os.path.join(out, f"fig4_timeseries_{ex}_run{a.example_run}.png"))

    pd.set_option("display.width", 220)
    pd.set_option("display.max_rows", 500)
    print(f"\nRuns analysed: {len(df)}  (warm-up excluded: first {a.warmup:g} s)\n")
    for m in ("rtt_mean_ms", "rtt_p95_ms", "goodput_mbps", "loss_events_window", "drops_total", "retx_total"):
        t = pt[pt.metric == m][["scenario", "baseline_mean", "proposed_mean", "diff_mean", "ci95_lo",
                                "ci95_hi", "rel_change_pct", "n_pairs", "verdict"]]
        print(f"=== {METRICS[m][0]} ===")
        print(t.round(3).to_string(index=False), "\n")
    print("Verdict tally over all scenario x metric pairs (excluding the neutral metric):")
    print(pt.verdict.value_counts().to_string())
    print(f"\nFiles written to {out}/")


if __name__ == "__main__":
    main()
