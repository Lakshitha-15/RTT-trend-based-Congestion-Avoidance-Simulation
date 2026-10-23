#!/usr/bin/env python3
"""
interpret.py -- automatically generated FACTUAL summary of one scenario.

Every sentence is produced from numbers in the paired-difference table (95% t-interval of the
difference over runs with the same run number). Wording rules:
  * "lower"/"higher" is stated only when the 95% interval excludes zero;
  * otherwise the text says "no clear difference";
  * no sentence claims the proposed method is "better" overall.
"""
import numpy as np

# metric -> (name, unit, decimals)
KEY = [
    ("rtt_mean_ms", "mean RTT", "ms", 1),
    ("rtt_p95_ms", "95th percentile RTT", "ms", 1),
    ("goodput_mbps", "goodput", "Mbit/s", 2),
    ("loss_events_window", "loss-recovery events (steady state)", "", 1),
    ("retx_window", "retransmitted segments (steady state)", "", 1),
    ("queue_mean_pkts", "mean queue occupancy", "packets", 1),
    ("cwnd_mean_segs", "mean cwnd", "segments", 1),
    ("fairness_jain", "Jain fairness index", "", 3),
]


def _row(paired, scenario, comparison, metric):
    r = paired[(paired.scenario == scenario) & (paired.comparison == comparison) & (paired.metric == metric)]
    return None if r.empty else r.iloc[0]


def describe(paired, scenario, comparison="proposed-baseline"):
    a, b = comparison.split("-")
    out = []
    for key, name, unit, dec in KEY:
        r = _row(paired, scenario, comparison, key)
        if r is None or not np.isfinite(r.baseline_mean):
            continue
        u = f" {unit}" if unit else ""
        pct = f"{r.rel_change_pct:+.1f}%" if np.isfinite(r.rel_change_pct) else "n/a"
        ci = (f"95% CI of difference [{r.ci95_lo:+.{dec}f}, {r.ci95_hi:+.{dec}f}], n={int(r.n_pairs)}"
              if np.isfinite(r.ci95_lo) else f"n={int(r.n_pairs)}")
        if not np.isfinite(r.ci95_lo) or r.ci95_lo <= 0 <= r.ci95_hi:
            verdict = "no clear difference"
        else:
            verdict = f"{a} {'higher' if r.diff_mean > 0 else 'lower'}"
        out.append(f"**{name}**: {b} {r.baseline_mean:.{dec}f}{u} -> {a} {r.proposed_mean:.{dec}f}{u} "
                   f"({pct}; {ci}): {verdict}.")
    return out


def observations(paired, summary, scenario):
    """Rule-based factual remarks (only if the numbers support them)."""
    obs = []
    S = summary[summary.scenario == scenario].set_index("algo")
    if "baseline" not in S.index or "proposed" not in S.index:
        return obs
    b, p = S.loc["baseline"], S.loc["proposed"]
    if b.loss_events_total_mean == 0 and p.loss_events_total_mean == 0:
        obs.append("No loss-recovery event occurred in either algorithm: this scenario is uncongested at the "
                   "bottleneck.")
        if np.isfinite(p.frac_early_mean):
            obs.append(f"Detector exposure in an uncongested run: the proposed algorithm spent "
                       f"{100 * p.frac_early_mean:.1f}% of the time in EARLY_CONGESTION and "
                       f"{100 * p.frac_congested_mean:.1f}% in CONGESTED, with {p.early_entries_mean:.1f} "
                       f"trend-triggered entries per run (every such entry is a false alarm here).")
    r = _row(paired, scenario, "proposed-baseline", "goodput_mbps")
    if r is not None and np.isfinite(r.baseline_mean) and r.baseline_mean > 0:
        if abs(r.rel_change_pct) < 1.0:
            obs.append(f"Throughput changed by {r.rel_change_pct:+.2f}% (below 1%).")
        elif np.isfinite(r.ci95_lo) and not (r.ci95_lo <= 0 <= r.ci95_hi):
            obs.append(f"Throughput changed by {r.rel_change_pct:+.1f}% (95% interval excludes zero).")
    if p.fairness_jain_mean < b.fairness_jain_mean - 0.05 and b.n_flows_mean > 1:
        obs.append(f"Fairness between flows is lower with the proposed algorithm: Jain index "
                   f"{b.fairness_jain_mean:.2f} -> {p.fairness_jain_mean:.2f}.")
    if "noslope" in S.index:
        r = _row(paired, scenario, "proposed-noslope", "rtt_mean_ms")
        if r is not None and np.isfinite(r.diff_mean):
            same = (not np.isfinite(r.ci95_lo)) or (r.ci95_lo <= 0 <= r.ci95_hi)
            obs.append(f"Ablation: disabling the slope trigger changes mean RTT by {-r.diff_mean:+.1f} ms "
                       f"({'no clear difference' if same else 'interval excludes zero'}); "
                       f"time in EARLY_CONGESTION {100 * p.frac_early_mean:.1f}% (full) vs "
                       f"{100 * S.loc['noslope'].frac_early_mean:.1f}% (slope trigger disabled).")
    if "monitor" in S.index and np.isfinite(S.loc["monitor"].warned_loss_frac_mean):
        m = S.loc["monitor"]
        lead = f"{m.lead_median_s_mean:.1f} s" if np.isfinite(m.lead_median_s_mean) else "n/a"
        obs.append(f"Detection (monitor-only runs, baseline trajectory): {100 * m.warned_loss_frac_mean:.0f}% of "
                   f"steady-state loss events were preceded by an early warning; median lead time {lead}.")
    return obs
