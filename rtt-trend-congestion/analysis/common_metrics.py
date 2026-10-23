#!/usr/bin/env python3
"""
common_metrics.py -- shared helpers used by the Part 2 analysis scripts.

Everything here only READS CSV files written by the NS-3 simulation (rtt-baseline) and computes
summary statistics. No values are simulated or invented.

Per-run metrics are computed over the interval [warmup, simTime] so that the start-up phase
(slow start, flows joining) does not dominate steady-state numbers. Whole-run loss counts are
reported separately.
"""
import os

import numpy as np
import pandas as pd

LOSS_STATES = ("CA_RECOVERY", "CA_LOSS")


# ------------------------------------------------------------------ basic readers
def read_csv(run_dir, name):
    """Read <run_dir>/<name>.csv; return an empty DataFrame if missing or header-only."""
    path = os.path.join(run_dir, f"{name}.csv")
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return pd.DataFrame()
    return pd.read_csv(path)


def read_summary(run_dir):
    """summary.csv (key,value) -> dict; numeric values converted to float."""
    df = pd.read_csv(os.path.join(run_dir, "summary.csv"))
    out = {}
    for k, v in zip(df["key"], df["value"]):
        try:
            out[k] = float(v)
        except (TypeError, ValueError):
            out[k] = v
    return out


# ------------------------------------------------------------------ statistics helpers
def weighted_quantile(values, weights, q):
    """Quantile q in [0,1] of 'values' with non-negative 'weights'."""
    values = np.asarray(values, dtype=float)
    weights = np.asarray(weights, dtype=float)
    if len(values) == 0 or weights.sum() <= 0:
        return float("nan")
    order = np.argsort(values)
    v, w = values[order], weights[order]
    cum = np.cumsum(w) - 0.5 * w
    return float(np.interp(q * w.sum(), cum, v))


def step_series(df, tcol, vcol, t0, t1):
    """
    A trace that is only written when a value CHANGES (queue, cwnd) is a step function.
    Return (values, durations) of its pieces restricted to [t0, t1].
    """
    if df.empty:
        return np.array([]), np.array([])
    t = df[tcol].to_numpy(dtype=float)
    v = df[vcol].to_numpy(dtype=float)
    # value in force at t0 = last change at or before t0
    idx = np.searchsorted(t, t0, side="right") - 1
    v0 = v[idx] if idx >= 0 else 0.0
    keep = (t > t0) & (t < t1)
    times = np.concatenate([[t0], t[keep], [t1]])
    vals = np.concatenate([[v0], v[keep]])
    return vals, np.diff(times)


def ols_slope(t, y):
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    if len(t) < 3:
        return float("nan")
    dt = t - t.mean()
    den = (dt ** 2).sum()
    return float((dt * (y - y.mean())).sum() / den) if den > 1e-12 else float("nan")


def jain_index(x):
    x = np.asarray(x, dtype=float)
    if len(x) == 0 or (x ** 2).sum() == 0:
        return float("nan")
    return float(x.sum() ** 2 / (len(x) * (x ** 2).sum()))


# ------------------------------------------------------------------ per-run metrics
def metrics_for_run(run_dir, warmup=10.0):
    s = read_summary(run_dir)
    sim_time = float(s["param.simTime"])
    n_flows = int(s["param.nFlows"])
    seg = float(s["param.segmentSize"])
    t0, t1 = float(warmup), sim_time
    m = {"variant": s["param.tcpVariant"], "n_flows": n_flows, "sim_time": sim_time,
         "warmup": t0}

    # ---- RTT (ns-3 'RTT' trace = RFC 6298 smoothed RTT, one value per ACK) ----
    rtt = read_csv(run_dir, "rtt")
    r = rtt[(rtt.time_s >= t0) & (rtt.time_s <= t1)] if not rtt.empty else rtt
    if r.empty:
        for k in ("rtt_mean_ms", "rtt_median_ms", "rtt_p95_ms", "rtt_std_ms",
                  "rtt_slope_abs_mean", "rtt_rising_frac"):
            m[k] = float("nan")
    else:
        m["rtt_mean_ms"] = float(r.rtt_ms.mean())
        m["rtt_median_ms"] = float(r.rtt_ms.median())
        m["rtt_p95_ms"] = float(r.rtt_ms.quantile(0.95))
        m["rtt_std_ms"] = float(r.rtt_ms.std())
        # RTT trend: OLS slope inside consecutive 1-second bins, per flow
        slopes = []
        for _, g in r.groupby("flow"):
            bins = np.floor(g.time_s.to_numpy() - t0).astype(int)
            for b in np.unique(bins):
                sel = bins == b
                if sel.sum() >= 10:
                    slopes.append(ols_slope(g.time_s.to_numpy()[sel], g.rtt_ms.to_numpy()[sel]))
        slopes = np.array([x for x in slopes if np.isfinite(x)])
        m["rtt_slope_abs_mean"] = float(np.abs(slopes).mean()) if len(slopes) else float("nan")
        m["rtt_rising_frac"] = float((slopes >= 2.0).mean()) if len(slopes) else float("nan")

    # ---- queueing delay at the bottleneck (ground truth, per departing packet) ----
    qd = read_csv(run_dir, "queue_delay")
    q = qd[(qd.time_s >= t0) & (qd.time_s <= t1)] if not qd.empty else qd
    m["qdelay_mean_ms"] = float(q.sojourn_ms.mean()) if not q.empty else float("nan")
    m["qdelay_p95_ms"] = float(q.sojourn_ms.quantile(0.95)) if not q.empty else float("nan")

    # ---- queue occupancy (time-weighted) ----
    vals, dur = step_series(read_csv(run_dir, "queue"), "time_s", "queue_packets", t0, t1)
    m["queue_mean_pkts"] = float(np.average(vals, weights=dur)) if dur.sum() > 0 else float("nan")
    m["queue_p95_pkts"] = weighted_quantile(vals, dur, 0.95)
    m["queue_max_pkts"] = float(vals.max()) if len(vals) else float("nan")

    # ---- throughput (receiver goodput, aggregate over flows) ----
    tp = read_csv(run_dir, "throughput")
    w = tp[(tp.time_s > t0) & (tp.time_s <= t1)]
    if w.empty:
        m["goodput_mbps"] = m["fairness_jain"] = float("nan")
    else:
        m["goodput_mbps"] = float(w.groupby("time_s").goodput_mbps.sum().mean())
        m["fairness_jain"] = jain_index(w.groupby("flow").goodput_mbps.mean().to_numpy())

    # ---- losses and retransmissions ----
    drops = read_csv(run_dir, "drops")
    m["drops_total"] = float(s["bottleneck.dropped_packets"])
    m["drops_window"] = float(((drops.time_s >= t0) & (drops.time_s <= t1)).sum()) if not drops.empty else 0.0
    m["drop_rate_pct"] = float(s["bottleneck.drop_rate_percent"])
    retx = read_csv(run_dir, "retransmissions")
    m["retx_total"] = float(s.get("trace.retransmitted_segments", len(retx)))
    m["retx_window"] = float(((retx.time_s >= t0) & (retx.time_s <= t1)).sum()) if not retx.empty else 0.0
    st = read_csv(run_dir, "cong_state")
    if st.empty:
        m["loss_events_total"] = m["loss_events_window"] = 0.0
    else:
        ev = st[st.new_state.isin(LOSS_STATES)]
        m["loss_events_total"] = float(len(ev))
        m["loss_events_window"] = float(((ev.time_s >= t0) & (ev.time_s <= t1)).sum())

    # ---- congestion window (per-flow time-weighted mean, averaged over flows) ----
    cw = read_csv(run_dir, "cwnd")
    means = []
    for _, g in cw.groupby("flow"):
        vals, dur = step_series(g, "time_s", "cwnd_bytes", t0, t1)
        if dur.sum() > 0:
            means.append(np.average(vals, weights=dur) / seg)
    m["cwnd_mean_segs"] = float(np.mean(means)) if means else float("nan")

    # ---- state-machine statistics (only meaningful for TcpRttTrend) ----
    trend = read_csv(run_dir, "rtt_trend")
    if trend.empty:
        m["frac_early"] = m["frac_congested"] = float("nan")
        m["early_entries"] = m["delay_congested_entries"] = float("nan")
    else:
        fr_e, fr_c = [], []
        for _, g in trend.groupby("flow"):
            t = g.time_s.to_numpy()
            dur = np.diff(np.concatenate([t, [t1]]))
            sel = (t >= t0) & (t <= t1)
            if dur[sel].sum() > 0:
                fr_e.append(dur[sel][g.state.to_numpy()[sel] == "EARLY_CONGESTION"].sum() / dur[sel].sum())
                fr_c.append(dur[sel][g.state.to_numpy()[sel] == "CONGESTED"].sum() / dur[sel].sum())
        m["frac_early"] = float(np.mean(fr_e)) if fr_e else float("nan")
        m["frac_congested"] = float(np.mean(fr_c)) if fr_c else float("nan")
        ev = read_csv(run_dir, "rtt_trend_events")
        if ev.empty:
            m["early_entries"] = m["delay_congested_entries"] = 0.0
        else:
            ev = ev[(ev.time_s >= t0) & (ev.time_s <= t1)]
            m["early_entries"] = float(((ev.new_state == "EARLY_CONGESTION") & (ev.reason == "rtt_trend")).sum())
            m["delay_congested_entries"] = float(((ev.new_state == "CONGESTED") & (ev.reason == "queue_delay")).sum())
    return m


# ------------------------------------------------------------------ batch helpers
_T975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306,
         9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131,
         20: 2.086, 30: 2.042}


def t_crit(df):
    """Two-sided 95% Student-t critical value for 'df' degrees of freedom."""
    if df < 1:
        return float("nan")
    keys = sorted(_T975)
    for k in keys:
        if df <= k:
            return _T975[k]
    return 1.96


def paired_ci(diffs):
    """Mean of paired differences with a 95% t-confidence interval -> (mean, lo, hi, n)."""
    d = np.asarray([x for x in diffs if np.isfinite(x)], dtype=float)
    n = len(d)
    if n == 0:
        return float("nan"), float("nan"), float("nan"), 0
    mean = d.mean()
    if n < 2:
        return float(mean), float("nan"), float("nan"), n
    half = t_crit(n - 1) * d.std(ddof=1) / np.sqrt(n)
    return float(mean), float(mean - half), float(mean + half), n


def collect_runs(root, warmup=10.0, cache=True, recompute=False):
    """
    Walk <root>/<scenario>/<label>/run<k>/ and compute metrics for every run.
    Returns a DataFrame with columns scenario, label, run + all metrics.
    The result is cached in <root>/metrics_per_run.csv (delete it or use recompute=True to refresh).
    """
    cache_path = os.path.join(root, "metrics_per_run.csv")
    if cache and not recompute and os.path.exists(cache_path):
        return pd.read_csv(cache_path)
    rows = []
    for scenario in sorted(os.listdir(root)):
        sdir = os.path.join(root, scenario)
        if not os.path.isdir(sdir) or scenario == "analysis":
            continue
        for label in sorted(os.listdir(sdir)):
            ldir = os.path.join(sdir, label)
            if not os.path.isdir(ldir):
                continue
            for run in sorted(os.listdir(ldir)):
                rdir = os.path.join(ldir, run)
                if not os.path.exists(os.path.join(rdir, "summary.csv")):
                    continue
                m = metrics_for_run(rdir, warmup)
                m.update(scenario=scenario, label=label, run=int(run.replace("run", "")))
                rows.append(m)
    df = pd.DataFrame(rows)
    if cache and not df.empty:
        df.to_csv(cache_path, index=False)
    return df
