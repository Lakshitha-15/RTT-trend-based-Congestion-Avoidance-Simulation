#!/usr/bin/env python3
"""
verify_consistency.py -- logical-consistency checks of the implementation, run on real results.

  python3 analysis/verify_consistency.py --config configs/main.json

Checks (all use kept raw traces of run 1 and the per-run metric table):
  A. FAIR COMPARISON   every algorithm of a scenario was run with identical scenario parameters
  B. MONITOR == BASELINE   the detector in monitor-only mode must not change the trajectory:
                           7 trace files byte-identical (run 1) and equal metrics (all runs)
  C. PHYSICS           min RTT >= propagation RTT; goodput <= payload capacity; queue <= limit;
                       queueing delay <= buffer drain time; drops only when the queue is full
  D. ACCOUNTING        goodput bins integrate to the bytes received; retransmissions >= drops
  E. STATE MACHINE     per flow, transition log is a connected chain; only allowed transitions;
                       every 'loss' transition coincides with a TCP loss-recovery entry
Exit code 1 if any check FAILS (warnings do not fail).
"""
import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import metrics as M  # noqa: E402

ALGO_KEYS = ("param.tcpVariant", "param.rttWindow", "param.rttAlpha", "param.slopeEnter", "param.slopeExit",
             "param.persistTime", "param.minQueueDelayMs", "param.congDelayMs", "param.exitFraction",
             "param.growthReduction", "param.congestedDecrease", "param.decreaseIntervalRtts",
             "param.minCwndSegs", "param.maxCwndSegs", "param.run")
ALLOWED = {("NORMAL", "EARLY_CONGESTION"), ("NORMAL", "CONGESTED"), ("EARLY_CONGESTION", "NORMAL"),
           ("EARLY_CONGESTION", "CONGESTED"), ("CONGESTED", "EARLY_CONGESTION")}
IDENT_FILES = ["cwnd", "rtt", "queue", "drops", "throughput", "cong_state", "retransmissions"]

counts = {"PASS": 0, "FAIL": 0, "WARN": 0}


def report(ok, msg, warn_only=False):
    tag = "PASS" if ok else ("WARN" if warn_only else "FAIL")
    counts[tag] += 1
    if tag != "PASS":
        print(f"  [{tag}] {msg}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    ap.add_argument("--data-dir", default=os.path.join(ROOT, "data"))
    a = ap.parse_args()
    cfg = json.load(open(a.config))
    suite = cfg["name"]
    raw = os.path.join(a.data_dir, "raw", suite)
    df = pd.read_csv(os.path.join(a.data_dir, "processed", suite, "metrics_per_run.csv"))

    for sc in cfg["scenarios"]:
        if sc not in set(df.scenario):
            continue
        print(f"{sc}")
        dirs = {al: os.path.join(raw, sc, al, "run1") for al in cfg["algorithms"]}
        dirs = {al: d for al, d in dirs.items() if M.has_run(d)}
        sums = {al: M.read_summary(d) for al, d in dirs.items()}

        # A. identical scenario parameters
        ref = next(iter(sums.values()))
        for al, s in sums.items():
            diff = [k for k in ref if k.startswith("param.") and k not in ALGO_KEYS and ref[k] != s.get(k)]
            report(not diff, f"{al}: scenario parameters differ from the others: {diff}")

        # B. monitor == baseline
        if "monitor" in dirs and "baseline" in dirs:
            for f in IDENT_FILES:
                x, y = M.read_csv(dirs["baseline"], f), M.read_csv(dirs["monitor"], f)
                report(x.equals(y), f"monitor and baseline differ in {f}.csv (run 1)")
            for k in ("rtt_mean_ms", "goodput_mbps", "drops_total", "retx_total", "cwnd_mean_segs", "queue_mean_pkts"):
                x = df[(df.scenario == sc) & (df.algo == "baseline")].sort_values("run")[k].to_numpy()
                y = df[(df.scenario == sc) & (df.algo == "monitor")].sort_values("run")[k].to_numpy()
                report(len(x) == len(y) and np.allclose(x, y, rtol=0, atol=1e-9, equal_nan=True),
                       f"monitor and baseline metric {k} differ in some run")

        for al, d in dirs.items():
            s = sums[al]
            seg = s["param.segmentSize"]
            bw = M.parse_mbps(s["param.bottleneckBw"])
            T = s["param.simTime"]
            base_rtt = 2 * (2 * M.parse_ms(s["param.accessDelay"]) + M.parse_ms(s["param.bottleneckDelay"]))
            qlim = s["param.queuePackets"]
            rtt, q = M.read_csv(d, "rtt"), M.read_csv(d, "queue")
            tp, dr, qd = M.read_csv(d, "throughput"), M.read_csv(d, "drops"), M.read_csv(d, "queue_delay")
            # C. physics
            report(rtt.rtt_ms.min() >= 0.97 * base_rtt, f"{al}: min RTT {rtt.rtt_ms.min():.2f} < propagation RTT {base_rtt}")
            payload_cap = bw * seg / (seg + 52.0)
            agg = tp.groupby("time_s").goodput_mbps.sum()
            # After a loss the receiver may deliver a burst of previously out-of-order data. At most
            # (queue + BDP + 10) segments can be in flight, so in a window of tau seconds
            #   goodput <= C_payload + (in-flight bound in bits) / tau.
            bdp_pkts = bw * 1e6 * base_rtt / 1000.0 / ((seg + 52) * 8.0)
            burst_bits = (qlim + bdp_pkts + 10) * seg * 8.0
            tau = 1.0
            report(agg.rolling(int(tau / s["param.throughputInterval"])).mean().max()
                   <= payload_cap + burst_bits / tau / 1e6,
                   f"{al}: 1 s goodput exceeds capacity + reordering burst bound")
            report(agg.mean() <= payload_cap, f"{al}: whole-run mean goodput exceeds payload capacity")
            report(q.queue_packets.max() <= qlim, f"{al}: queue exceeded its limit")
            drain_ms = qlim * (seg + 52 + 2) * 8 / (bw * 1e6) * 1000
            report(qd.sojourn_ms.max() <= 1.03 * drain_ms, f"{al}: queueing delay above buffer drain time")
            if len(dr):
                report(q.queue_packets.max() == qlim, f"{al}: drops occurred but the queue never reached its limit")
            # D. accounting
            delivered = sum(s[f"flow{i}.bytes_received"] for i in range(int(s["param.nFlows"])))
            integ = (tp.goodput_mbps * 1e6 / 8 * s["param.throughputInterval"]).sum()
            report(abs(integ - delivered) <= 0.01 * max(delivered, 1) + 3 * seg,
                   f"{al}: goodput bins integrate to {integ:.0f} B but receivers got {delivered:.0f} B")
            report(s["trace.retransmitted_segments"] >= s["bottleneck.dropped_packets"] * 0.95 or s["bottleneck.dropped_packets"] == 0,
                   f"{al}: fewer retransmissions than drops", warn_only=True)
            # E. state machine
            ev, tr, st = M.read_csv(d, "rtt_trend_events"), M.read_csv(d, "rtt_trend"), M.read_csv(d, "cong_state")
            if al != "baseline" and not tr.empty:
                for f, g in ev.groupby("flow"):
                    pairs = list(zip(g.old_state, g.new_state))
                    report(all(p in ALLOWED for p in pairs), f"{al} flow {f}: transition outside the state machine")
                    chain = (g.old_state.to_numpy()[1:] == g.new_state.to_numpy()[:-1]).all() if len(g) > 1 else True
                    report(chain, f"{al} flow {f}: transition chain is broken")
                    losses = st[(st.flow == f) & st.new_state.isin(M.LOSS_STATES)].time_s.to_numpy()
                    for t in g[g.reason == "loss"].time_s:
                        report(np.min(np.abs(losses - t)) < 1e-6 if len(losses) else False,
                               f"{al} flow {f}: 'loss' transition at {t:.3f}s without TCP loss entry")
                last = tr.groupby("flow").tail(1)
                for _, r in last.iterrows():
                    g = ev[ev.flow == r.flow]
                    expect = g.new_state.iloc[-1] if len(g) else "NORMAL"
                    report(expect == r.state or r.time_s < g.time_s.max() if len(g) else r.state == "NORMAL",
                           f"{al} flow {int(r.flow)}: final logged state {r.state} disagrees with transition log")
    print(f"\nconsistency checks: {counts['PASS']} passed, {counts['WARN']} warnings, {counts['FAIL']} failed")
    sys.exit(1 if counts["FAIL"] else 0)


if __name__ == "__main__":
    main()
