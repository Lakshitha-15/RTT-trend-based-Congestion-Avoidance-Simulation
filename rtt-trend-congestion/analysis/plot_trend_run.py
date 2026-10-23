#!/usr/bin/env python3
"""
plot_trend_run.py -- inspect ONE run of the proposed algorithm (for debugging / the viva).

  python3 analysis/plot_trend_run.py results/baseline_or_any_run_dir [--flow 0]

Needs a run made with --tcpVariant=TcpRttTrend (rtt_trend.csv must contain rows).
Shows: RTT (per ACK) with the per-RTT smoothed value and the base RTT, the regression slope with
the entry/exit thresholds, cwnd, the state timeline, and the bottleneck queue.
"""
import argparse
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common_metrics import read_csv, read_summary  # noqa: E402

STATE_Y = {"NORMAL": 0, "EARLY_CONGESTION": 1, "CONGESTED": 2}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--flow", type=int, default=0)
    a = ap.parse_args()

    s = read_summary(a.run_dir)
    tr = read_csv(a.run_dir, "rtt_trend")
    if tr.empty:
        sys.exit("rtt_trend.csv is empty: run the simulation with --tcpVariant=TcpRttTrend")
    tr = tr[tr.flow == a.flow]
    rtt = read_csv(a.run_dir, "rtt")
    rtt = rtt[rtt.flow == a.flow]
    cw = read_csv(a.run_dir, "cwnd")
    cw = cw[cw.flow == a.flow]
    q = read_csv(a.run_dir, "queue")
    ev = read_csv(a.run_dir, "cong_state")
    seg = s["param.segmentSize"]

    fig, ax = plt.subplots(5, 1, figsize=(13, 13), sharex=True,
                           gridspec_kw={"height_ratios": [2, 1.5, 1.5, 0.7, 1.2]})
    ax[0].plot(rtt.time_s, rtt.rtt_ms, lw=0.5, c="lightgray", label="RTT value per ACK (ns-3)")
    ax[0].plot(tr.time_s, tr.rtt_in_ms, ".", ms=3, c="tab:blue", label="per-RTT sample (epoch mean)")
    ax[0].plot(tr.time_s, tr.smoothed_ms, c="tab:orange", lw=1.2, label="EWMA-smoothed")
    ax[0].plot(tr.time_s, tr.base_rtt_ms, c="green", ls="--", lw=0.8, label="base RTT (min)")
    ax[0].set_ylabel("RTT [ms]")
    ax[1].plot(tr.time_s, tr.slope_ms_per_s, c="tab:purple", lw=1, label="regression slope")
    ax[1].axhline(s["param.slopeEnter"], c="red", ls="--", lw=0.8, label="enter")
    ax[1].axhline(s["param.slopeExit"], c="green", ls="--", lw=0.8, label="exit")
    ax[1].axhline(0, c="gray", lw=0.5)
    ax[1].set_ylim(-15, 25)
    ax[1].set_ylabel("slope [ms/s]")
    ax[2].step(cw.time_s, cw.cwnd_bytes / seg, where="post", lw=0.8)
    ax[2].set_ylabel("cwnd [segments]")
    ax[3].step(tr.time_s, tr.state.map(STATE_Y), where="post", c="black")
    ax[3].set_yticks([0, 1, 2])
    ax[3].set_yticklabels(["NORMAL", "EARLY", "CONGESTED"])
    for t in ev[ev.new_state.isin(["CA_RECOVERY", "CA_LOSS"])].time_s:
        ax[3].axvline(t, c="red", alpha=0.5, lw=1)
    ax[3].set_ylabel("state\n(red line = loss)")
    ax[4].step(q.time_s, q.queue_packets, where="post", lw=0.5)
    ax[4].set_ylabel("queue [packets]")
    ax[4].set_xlabel("time [s]")
    for x in (ax[0], ax[1]):
        x.legend(fontsize=8, loc="upper right")
    for x in ax:
        x.grid(alpha=0.3)
    ax[0].set_title(f"{s['param.tcpVariant']}  flow {a.flow}  |  {a.run_dir}")
    fig.tight_layout()
    out = os.path.join(a.run_dir, "trend_run.png")
    fig.savefig(out, dpi=120)
    print("written", out)


if __name__ == "__main__":
    main()
