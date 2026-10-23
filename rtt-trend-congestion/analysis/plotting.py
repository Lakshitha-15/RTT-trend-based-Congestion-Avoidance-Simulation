#!/usr/bin/env python3
"""
plotting.py -- all Matplotlib figures of the project (used by analyze.py AND the Streamlit dashboard).

Every function takes run directories / DataFrames produced by the simulation and returns a
matplotlib Figure. No values are typed in by hand.
  runs : dict  algorithm label -> run directory   (e.g. {"baseline": ".../run1", "proposed": ".../run1"})
"""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import metrics as M

COLORS = {"baseline": "#4C72B0", "proposed": "#DD8452", "noslope": "#55A868", "monitor": "#7F7F7F"}
LABELS = {"baseline": "Baseline (TcpNewReno)", "proposed": "Proposed (TcpRttTrend)",
          "noslope": "Ablation: delay threshold only", "monitor": "Baseline + detector observing (no response)"}
STATE_COLORS = {"NORMAL": "#FFFFFF", "EARLY_CONGESTION": "#FFD28A", "CONGESTED": "#F4A09C"}
STATE_Y = {"NORMAL": 0, "EARLY_CONGESTION": 1, "CONGESTED": 2}


def _style(ax, title=None, xlabel=None, ylabel=None, legend=True):
    if title:
        ax.set_title(title, fontsize=11, fontweight="bold")
    if xlabel:
        ax.set_xlabel(xlabel)
    if ylabel:
        ax.set_ylabel(ylabel)
    ax.grid(alpha=0.3)
    if legend and ax.get_legend_handles_labels()[0]:
        ax.legend(fontsize=8, loc="best")


def _lab(a):
    return LABELS.get(a, a)


def _flow(df, flow):
    return df if df.empty or flow is None else df[df.flow == flow]


def _seg(runs):
    return M.read_summary(next(iter(runs.values())))["param.segmentSize"]


def _shade_states(ax, trend):
    """Shade EARLY / CONGESTED periods of one flow's rtt_trend.csv on an axis."""
    if trend.empty:
        return
    t = trend.time_s.to_numpy()
    st = trend.state.to_numpy()
    start = 0
    for i in range(1, len(t) + 1):
        if i == len(t) or st[i] != st[start]:
            if st[start] != "NORMAL":
                ax.axvspan(t[start], t[i] if i < len(t) else t[-1], color=STATE_COLORS[st[start]],
                           alpha=0.45, lw=0)
            start = i


# ------------------------------------------------------------------ per-run time series
def fig_rtt(runs, flow=0, title=""):
    fig, ax = plt.subplots(figsize=(11, 4))
    for a, d in runs.items():
        r = _flow(M.read_csv(d, "rtt"), flow)
        if not r.empty:
            ax.plot(r.time_s, r.rtt_ms, lw=0.8, color=COLORS.get(a), label=_lab(a))
    s = M.read_summary(next(iter(runs.values())))
    base = 2 * (2 * M.parse_ms(s["param.accessDelay"]) + M.parse_ms(s["param.bottleneckDelay"]))
    ax.axhline(base, ls="--", c="gray", lw=0.8, label=f"propagation RTT ({base:g} ms)")
    _style(ax, f"RTT vs time {title}".strip(), "time [s]", "RTT [ms]  (ns-3 RTT estimate, one value per ACK)")
    fig.tight_layout()
    return fig


def fig_trend(runs, flow=0, title=""):
    """Smoothed RTT, regression slope with thresholds, and congestion state (algorithms with a detector)."""
    algos = [a for a in ("monitor", "proposed", "noslope") if a in runs]
    fig, ax = plt.subplots(3, 1, figsize=(11, 8.5), sharex=True, gridspec_kw={"height_ratios": [2, 2, 1]})
    if not algos:
        ax[0].text(0.5, 0.5, "select an algorithm with a detector (monitor / proposed / noslope)",
                   ha="center", transform=ax[0].transAxes)
        return fig
    s = M.read_summary(runs[algos[0]])
    for i, a in enumerate(algos):
        tr = _flow(M.read_csv(runs[a], "rtt_trend"), flow)
        if tr.empty:
            continue
        ax[0].plot(tr.time_s, tr.smoothed_ms, color=COLORS[a], lw=1.1, label=_lab(a))
        ax[1].plot(tr.time_s, tr.slope_ms_per_s, color=COLORS[a], lw=1.0, label=_lab(a))
        # small vertical offset per algorithm so that identical state curves stay visible
        ax[2].step(tr.time_s, tr.state.map(STATE_Y) + 0.09 * (i - (len(algos) - 1) / 2), where="post",
                   color=COLORS[a], lw=1.6, label=_lab(a))
    base_tr = _flow(M.read_csv(runs[algos[0]], "rtt_trend"), flow)
    if not base_tr.empty:
        ax[0].plot(base_tr.time_s, base_tr.base_rtt_ms, "k:", lw=1.0, label="base RTT (min of smoothed)")
    ax[1].axhline(s["param.slopeEnter"], c="red", ls="--", lw=0.9, label=f"enter threshold ({s['param.slopeEnter']:g} ms/s)")
    ax[1].axhline(s["param.slopeExit"], c="green", ls="--", lw=0.9, label=f"exit threshold ({s['param.slopeExit']:g} ms/s)")
    ax[1].axhline(0, c="gray", lw=0.5)
    ax[1].set_ylim(-15, 25)
    ax[2].set_yticks([0, 1, 2])
    ax[2].set_yticklabels(["NORMAL", "EARLY", "CONGESTED"])
    _style(ax[0], f"Smoothed RTT {title}".strip(), None, "smoothed RTT [ms]")
    _style(ax[1], "RTT trend (regression slope over the sliding window)", None, "slope [ms/s]")
    _style(ax[2], "Congestion state (curves offset vertically for visibility)", "time [s]", "state")
    fig.tight_layout()
    return fig


def fig_cwnd(runs, flow=0, title=""):
    fig, ax = plt.subplots(figsize=(11, 4))
    seg = _seg(runs)
    for a, d in runs.items():
        c = _flow(M.read_csv(d, "cwnd"), flow)
        if not c.empty:
            ax.step(c.time_s, c.cwnd_bytes / seg, where="post", lw=0.9, color=COLORS.get(a), label=_lab(a))
    _style(ax, f"Congestion window vs time {title}".strip(), "time [s]", "cwnd [segments]")
    fig.tight_layout()
    return fig


def fig_throughput_loss(runs, title=""):
    fig, ax = plt.subplots(2, 1, figsize=(11, 6.5), sharex=True)
    for a, d in runs.items():
        tp = M.read_csv(d, "throughput")
        if not tp.empty:
            agg = tp.groupby("time_s").goodput_mbps.sum()
            ax[0].plot(agg.index, agg.rolling(10, min_periods=1).mean(), lw=1.1, color=COLORS.get(a), label=_lab(a))
        dr = M.read_csv(d, "drops")
        if not dr.empty:
            ax[1].step(dr.time_s, dr.cumulative_drops, where="post", lw=1.2, color=COLORS.get(a), label=_lab(a))
        else:
            ax[1].plot([], [], color=COLORS.get(a), label=_lab(a) + " (no drops)")
    s = M.read_summary(next(iter(runs.values())))
    cap = M.parse_mbps(s["param.bottleneckBw"]) * s["param.segmentSize"] / (s["param.segmentSize"] + 52.0)
    ax[0].axhline(cap, ls="--", c="gray", lw=0.8, label=f"payload capacity ({cap:.2f} Mbit/s)")
    _style(ax[0], f"Aggregate goodput (1 s moving mean) {title}".strip(), None, "goodput [Mbit/s]")
    _style(ax[1], "Cumulative packets dropped at the bottleneck queue", "time [s]", "dropped packets")
    fig.tight_layout()
    return fig


def fig_queue(runs, title=""):
    fig, ax = plt.subplots(figsize=(11, 4))
    s = M.read_summary(next(iter(runs.values())))
    for a, d in runs.items():
        q = M.read_csv(d, "queue")
        if not q.empty:
            ax.step(q.time_s, q.queue_packets, where="post", lw=0.6, color=COLORS.get(a), label=_lab(a))
    ax.axhline(s["param.queuePackets"], ls="--", c="gray", lw=0.8, label=f"queue limit ({s['param.queuePackets']:g} packets)")
    _style(ax, f"Bottleneck queue occupancy {title}".strip(), "time [s]", "queue [packets]")
    fig.tight_layout()
    return fig


# ------------------------------------------------------------------ summary figures
METRIC_LABEL = {
    "rtt_mean_ms": "mean RTT [ms]", "rtt_median_ms": "median RTT [ms]", "rtt_p95_ms": "95th percentile RTT [ms]",
    "rtt_max_ms": "maximum RTT [ms]", "qdelay_mean_ms": "mean queueing delay [ms]",
    "qdelay_p95_ms": "95th pct queueing delay [ms]", "rtt_slope_abs_mean": "mean |RTT slope| [ms/s]",
    "goodput_mbps": "goodput [Mbit/s]", "utilization_pct": "link utilisation [%]",
    "loss_rate_pct": "packet loss rate, whole run [%]", "drops_total": "packets dropped, whole run",
    "drops_window": "packets dropped, steady state", "retx_total": "retransmitted segments, whole run",
    "retx_window": "retransmitted segments, steady state", "loss_events_window": "loss-recovery events, steady state",
    "cwnd_mean_segs": "mean cwnd [segments]", "cwnd_max_segs": "maximum cwnd [segments]",
    "queue_mean_pkts": "mean queue [packets]", "queue_p95_pkts": "95th pct queue [packets]",
    "fairness_jain": "Jain fairness index", "frac_early": "share of time in EARLY_CONGESTION",
    "frac_congested": "share of time in CONGESTED", "early_entries": "EARLY_CONGESTION entries (trend)",
    "first_warning_s": "first early warning after flow start [s]", "first_loss_s": "first loss after flow start [s]",
    "warned_loss_frac": "share of loss events preceded by a warning", "lead_median_s": "median warning lead time [s]",
}


def short(s):
    return s.split("_", 1)[0] + "\n" + s.split("_", 1)[1] if "_" in s else s


def fig_summary_bars(summary, scenarios, keys, algos=("baseline", "proposed", "noslope"), ncols=3):
    """summary: DataFrame with columns scenario, algo, <metric>_mean, <metric>_std."""
    nrows = int(np.ceil(len(keys) / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(6.2 * ncols, 3.8 * nrows), squeeze=False)
    x = np.arange(len(scenarios))
    w = 0.8 / len(algos)
    for ax, k in zip(axes.ravel(), keys):
        for i, a in enumerate(algos):
            s = summary[summary.algo == a].set_index("scenario").reindex(scenarios)
            ax.bar(x + (i - (len(algos) - 1) / 2) * w, s[k + "_mean"], w, yerr=s[k + "_std"].fillna(0), capsize=1.5,
                   color=COLORS.get(a), label=_lab(a))
        ax.set_xticks(x)
        ax.set_xticklabels([sc.split("_")[0] for sc in scenarios], fontsize=8)
        if k.startswith("cwnd"):
            # application-limited flows (S01, S02, S04) let cwnd grow without bound: use a log axis
            ax.set_yscale("log")
        _style(ax, METRIC_LABEL.get(k, k) + (" (log scale)" if k.startswith("cwnd") else ""), "scenario", None,
               legend=False)
    for ax in axes.ravel()[len(keys):]:
        ax.axis("off")
    axes[0, 0].legend(fontsize=7)
    fig.suptitle("Scenario summary: mean +- standard deviation over runs", fontsize=12, fontweight="bold")
    fig.tight_layout()
    return fig


def fig_paired(paired, scenarios, keys, comparison="proposed-baseline", ncols=3):
    nrows = int(np.ceil(len(keys) / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(6.2 * ncols, 3.8 * nrows), squeeze=False)
    x = np.arange(len(scenarios))
    for ax, k in zip(axes.ravel(), keys):
        t = paired[(paired.metric == k) & (paired.comparison == comparison)].set_index("scenario").reindex(scenarios)
        err = np.vstack([(t.diff_mean - t.ci95_lo).fillna(0), (t.ci95_hi - t.diff_mean).fillna(0)])
        ax.errorbar(x, t.diff_mean, yerr=err, fmt="o", capsize=3, color="black")
        ax.axhline(0, c="gray", lw=1)
        ax.set_xticks(x)
        ax.set_xticklabels([sc.split("_")[0] for sc in scenarios], fontsize=8)
        _style(ax, f"{METRIC_LABEL.get(k, k)}: difference", "scenario", None, legend=False)
    for ax in axes.ravel()[len(keys):]:
        ax.axis("off")
    a, b = comparison.split("-")
    fig.suptitle(f"Paired differences ({a} minus {b}) with 95% confidence intervals", fontsize=12, fontweight="bold")
    fig.tight_layout()
    return fig


def fig_tradeoff(summary, scenarios, algos=("baseline", "proposed")):
    fig, ax = plt.subplots(figsize=(8.5, 6))
    for sc in scenarios:
        pts = {}
        for a in algos:
            r = summary[(summary.scenario == sc) & (summary.algo == a)]
            if not r.empty:
                pts[a] = (r.iloc[0].rtt_p95_ms_mean, r.iloc[0].utilization_pct_mean)
        if len(pts) == 2:
            ax.annotate("", xy=pts[algos[1]], xytext=pts[algos[0]], arrowprops=dict(arrowstyle="->", color="gray"))
        for a, p in pts.items():
            ax.scatter(*p, c=COLORS[a], s=35)
        if algos[1] in pts:
            ax.text(pts[algos[1]][0], pts[algos[1]][1], " " + sc.split("_")[0], fontsize=7)
    for a in algos:
        ax.scatter([], [], c=COLORS[a], label=_lab(a))
    _style(ax, "Delay vs utilisation per scenario (arrow: baseline -> proposed)",
           "95th percentile RTT [ms]  (lower is better)", "link utilisation [%]  (higher is better)")
    fig.tight_layout()
    return fig


def fig_detection(summary, scenarios):
    """Detection behaviour measured on the monitor-only runs (trajectory identical to baseline)."""
    fig, ax = plt.subplots(1, 3, figsize=(16, 4.2))
    s = summary[summary.algo == "monitor"].set_index("scenario").reindex(scenarios)
    x = np.arange(len(scenarios))
    for a, k in zip(ax, ("warned_loss_frac", "lead_median_s", "first_warning_s")):
        a.bar(x, s[k + "_mean"], yerr=s[k + "_std"].fillna(0), capsize=2, color=COLORS["monitor"])
        a.set_xticks(x)
        a.set_xticklabels([sc.split("_")[0] for sc in scenarios], fontsize=8)
        _style(a, METRIC_LABEL[k], "scenario", None, legend=False)
    if "first_loss_s_mean" in s:
        ax[2].plot(x, s["first_loss_s_mean"], "rx", label="first loss (baseline trajectory)")
        ax[2].legend(fontsize=8)
    fig.suptitle("Early-warning behaviour of the detector (monitor-only runs = baseline trajectory)",
                 fontsize=12, fontweight="bold")
    fig.tight_layout()
    return fig


def fig_sensitivity(sens_summary, scenario, metrics_to_plot=("rtt_mean_ms", "utilization_pct", "loss_events_window",
                                                              "fairness_jain", "frac_early", "early_entries")):
    s = sens_summary[sens_summary.scenario == scenario]
    params = []
    for a in s.algo.unique():
        if "=" in a:
            p = a.split("=")[0]
            if p not in params:
                params.append(p)
    fig, axes = plt.subplots(len(params), len(metrics_to_plot), figsize=(3.4 * len(metrics_to_plot), 2.4 * len(params)),
                             squeeze=False)
    base = s[s.algo == "baseline"]
    default = s[s.algo == "default"]
    for i, p in enumerate(params):
        rows = s[s.algo.str.startswith(p + "=")].copy()
        rows["v"] = rows.algo.str.split("=").str[1].astype(float)
        rows = rows.sort_values("v")
        for j, k in enumerate(metrics_to_plot):
            ax = axes[i, j]
            ax.errorbar(rows.v, rows[k + "_mean"], yerr=rows[k + "_std"].fillna(0), fmt="o-", capsize=3, color=COLORS["proposed"])
            if not base.empty and not np.isnan(base.iloc[0][k + "_mean"]):
                ax.axhline(base.iloc[0][k + "_mean"], ls="--", c=COLORS["baseline"], lw=1, label="baseline")
            if not default.empty:
                ax.axhline(default.iloc[0][k + "_mean"], ls=":", c="black", lw=1, label="default")
            ax.grid(alpha=0.3)
            if i == 0:
                ax.set_title(METRIC_LABEL.get(k, k), fontsize=8)
            if j == 0:
                ax.set_ylabel(p, fontweight="bold", fontsize=9)
            ax.tick_params(labelsize=7)
    axes[0, 0].legend(fontsize=6)
    fig.suptitle(f"Parameter sensitivity, scenario {scenario} (mean +- std; dashed = baseline, dotted = default)",
                 fontsize=11, fontweight="bold")
    fig.tight_layout()
    return fig
