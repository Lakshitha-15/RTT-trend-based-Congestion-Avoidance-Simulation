#!/usr/bin/env python3
"""
plot_baseline.py -- verify and plot the PART 1 baseline output of rtt-baseline.

Usage (from the ns-3 root directory):
    python3 analysis/plot_baseline.py results/baseline
Produces <dir>/baseline_overview.png and prints sanity checks.
Only reads CSV files written by the simulation; nothing is generated or simulated here.
"""
import os
import re
import sys

import matplotlib
matplotlib.use("Agg")  # no display needed
import matplotlib.pyplot as plt
import pandas as pd


def parse_ms(text):
    """'20ms' -> 20.0, '2us' -> 0.002, '1s' -> 1000.0 (milliseconds)."""
    m = re.fullmatch(r"\s*([\d.]+)\s*(ms|us|s)\s*", text)
    return float(m.group(1)) * {"ms": 1.0, "us": 1e-3, "s": 1e3}[m.group(2)]


def parse_mbps(text):
    """'10Mbps' -> 10.0, '1Gbps' -> 1000.0, '500kbps' -> 0.5 (Mbit/s)."""
    m = re.fullmatch(r"\s*([\d.]+)\s*([kMG]?)bps\s*", text)
    return float(m.group(1)) * {"k": 1e-3, "": 1e-6, "M": 1.0, "G": 1e3}[m.group(2)]


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "results/baseline"
    needed = ["rtt", "cwnd", "throughput", "queue", "queue_delay", "drops", "cong_state"]
    for name in needed + ["summary"]:
        if not os.path.exists(f"{out}/{name}.csv"):
            sys.exit(f"Missing {out}/{name}.csv -- did the simulation finish?")

    rtt, cwnd, tput = (pd.read_csv(f"{out}/{n}.csv") for n in ("rtt", "cwnd", "throughput"))
    queue, qdelay, drops = (pd.read_csv(f"{out}/{n}.csv") for n in ("queue", "queue_delay", "drops"))
    state = pd.read_csv(f"{out}/cong_state.csv")
    summary = pd.read_csv(f"{out}/summary.csv").set_index("key")["value"]

    seg = float(summary["param.segmentSize"])
    bw = parse_mbps(summary["param.bottleneckBw"])
    qpk = int(summary["param.queuePackets"])
    base_rtt = 2 * (2 * parse_ms(summary["param.accessDelay"]) + parse_ms(summary["param.bottleneckDelay"]))
    ip_pkt_bytes = seg + 52  # 1448 payload + 20 IP + 20 TCP + 12 TCP timestamp option
    max_qdelay = qpk * ip_pkt_bytes * 8 / (bw * 1e6) * 1000  # ms
    sim_time = float(summary["param.simTime"])

    # ---------------- plots ----------------
    fig, ax = plt.subplots(2, 2, figsize=(14, 8), sharex=True)
    for f, g in rtt.groupby("flow"):
        ax[0, 0].plot(g.time_s, g.rtt_ms, lw=0.8, label=f"flow {f}")
    ax[0, 0].axhline(base_rtt, ls="--", c="gray", lw=0.8, label=f"propagation RTT {base_rtt:.0f} ms")
    ax[0, 0].set(title="RTT (ns-3 'RTT' trace) vs time", ylabel="RTT [ms]")
    ax[0, 0].legend(fontsize=8)

    for f, g in cwnd.groupby("flow"):
        ax[0, 1].step(g.time_s, g.cwnd_bytes / seg, where="post", lw=0.8, label=f"flow {f}")
    losses = state[state.new_state.isin(["CA_RECOVERY", "CA_LOSS"])]
    for t in losses.time_s:
        ax[0, 1].axvline(t, c="red", alpha=0.3, lw=0.8)
    ax[0, 1].set(title="Congestion window vs time (red = loss recovery entered)",
                 ylabel="cwnd [segments]")
    ax[0, 1].legend(fontsize=8)

    for f, g in tput.groupby("flow"):
        ax[1, 0].plot(g.time_s, g.goodput_mbps, lw=0.5, alpha=0.5, label=f"flow {f} (raw bins)")
        ax[1, 0].plot(g.time_s, g.goodput_mbps.rolling(10, min_periods=1).mean(), lw=1.4,
                      label=f"flow {f} (1 s mean)")
    ax[1, 0].axhline(bw, ls="--", c="gray", lw=0.8, label="bottleneck rate")
    ax[1, 0].set(title="Receiver goodput vs time", xlabel="time [s]", ylabel="goodput [Mbit/s]")
    ax[1, 0].legend(fontsize=8)

    ax[1, 1].step(queue.time_s, queue.queue_packets, where="post", lw=0.5)
    ax[1, 1].plot(drops.time_s, [qpk] * len(drops), "rx", ms=4, label="packet drops")
    ax[1, 1].axhline(qpk, ls="--", c="gray", lw=0.8)
    ax[1, 1].set(title="Bottleneck queue occupancy vs time", xlabel="time [s]",
                 ylabel="queue [packets]")
    ax[1, 1].legend(fontsize=8)

    fig.suptitle(f"Baseline {summary['param.tcpVariant']}  |  {out}", fontsize=11)
    fig.tight_layout()
    png = f"{out}/baseline_overview.png"
    fig.savefig(png, dpi=130)

    # ---------------- sanity checks ----------------
    print(f"\nPlot written to {png}\n")
    print("=== Summary from simulation ===")
    print(summary.to_string())
    print("\n=== Verification checks ===")

    def check(ok, msg):
        print(("[PASS] " if ok else "[WARN] ") + msg)

    check(all(len(d) > 0 for d in (rtt, cwnd, tput, queue)), "all main CSV files contain data")
    check(rtt.time_s.is_monotonic_increasing and cwnd.time_s.is_monotonic_increasing,
          "timestamps are non-decreasing")
    check(rtt.time_s.max() > 0.9 * sim_time, f"trace covers the run (last RTT sample at {rtt.time_s.max():.1f} s)")
    check(rtt.rtt_ms.min() >= 0.95 * base_rtt,
          f"min RTT {rtt.rtt_ms.min():.2f} ms >= propagation RTT {base_rtt:.1f} ms (cannot be lower)")
    check(rtt.rtt_ms.max() > 1.5 * base_rtt,
          f"RTT rises well above base: max {rtt.rtt_ms.max():.1f} ms (queueing visible)")
    check(rtt.rtt_ms.max() <= base_rtt + max_qdelay + 15,
          f"max RTT <= base + full-queue delay ({base_rtt + max_qdelay:.1f} ms) + slack")
    check(qdelay.sojourn_ms.max() <= max_qdelay * 1.05,
          f"max measured queueing delay {qdelay.sojourn_ms.max():.1f} ms <= bound {max_qdelay:.1f} ms")
    check(queue.queue_packets.max() == qpk, f"queue reached its limit ({qpk} packets)")
    check(len(drops) > 0, f"{len(drops)} packets dropped at the bottleneck (congestion occurred)")
    check(len(losses) > 0, f"{len(losses)} loss-recovery entries (fast retransmit / RTO)")
    total_gp = float(sum(float(summary[k]) for k in summary.index if k.endswith(".avg_goodput_mbps")))
    max_gp = bw * seg / ip_pkt_bytes
    check(total_gp <= max_gp * 1.02,
          f"total goodput {total_gp:.2f} Mbit/s <= payload capacity ~{max_gp:.2f} Mbit/s")
    check(total_gp >= 0.5 * bw, f"link reasonably utilised ({100 * total_gp / bw:.0f}% of {bw:.0f} Mbit/s)")

    print("\nCongestion-state transitions (retransmission-related events):")
    print(state.groupby("new_state").size().to_string())
    print("\nNOTE: the 'RTT' trace is what ns-3's RTT estimator reports for each ACK "
          "(treated as smoothed RTT), not a raw per-packet sample.")


if __name__ == "__main__":
    main()
