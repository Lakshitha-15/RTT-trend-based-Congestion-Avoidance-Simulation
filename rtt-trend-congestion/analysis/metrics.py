#!/usr/bin/env python3
"""
metrics.py -- every metric used in the project, computed ONLY from the CSV files written by the
NS-3 simulation (nothing is simulated, assumed or typed in by hand).

Definitions (all computed over the measurement window [t0, T] unless stated otherwise;
t0 = warm-up end, T = simulation time):

  RTT statistics     Pool all rows of rtt.csv in the window (one row per ACK, value = ns-3's smoothed
                     RTT, see README). mean, median, 95th percentile (linear interpolation), maximum.
  Queueing delay     Same statistics over queue_delay.csv (true per-packet sojourn time in the
                     bottleneck queue, measured by ns-3).
  RTT trend          Split each flow's rtt.csv into 1-second bins, take the OLS slope of RTT against
                     time in every bin (>= 10 samples) -> mean absolute slope [ms/s].
  Goodput            G = mean over 0.1 s bins of sum_f g_f(t)   [Mbit/s]  (bytes delivered to the
                     receiving applications). Utilisation = G / (C * MSS/(MSS+52)).
  Loss rate          Whole run: 100 * dropped / received packets at the bottleneck queue
                     (QueueDisc statistics). Window: number of drops in the window (drops.csv).
  Retransmissions    Data segments whose sequence number was already sent (retransmissions.csv),
                     whole run and window. Loss-recovery events = entries into CA_RECOVERY/CA_LOSS.
  Congestion window  Time-weighted mean of the step function cwnd(t), averaged over flows, and the
                     maximum value reached in the window [segments].
  Queue occupancy    Time-weighted mean / 95th percentile / maximum of queue(t) [packets].
  Fairness           Jain index J = (sum x_f)^2 / (n * sum x_f^2) of per-flow mean goodput.
  Detection          first_warning_s: time from a flow's start to its first early-warning event
                     (transition to EARLY_CONGESTION by RTT trend or to CONGESTED by queueing delay).
                     first_loss_s: time from the flow's start to its first loss-recovery event.
                     For every loss event in the window: was there a warning after the previous loss
                     (or flow start) and before this loss? -> warned_loss_frac; lead = t_loss - t_warn.
                     Only meaningful for the 'monitor' algorithm (its trajectory equals the baseline).
"""
import gzip
import os
import re

import numpy as np
import pandas as pd

LOSS_STATES = ("CA_RECOVERY", "CA_LOSS")


# ------------------------------------------------------------------ readers (plain or .gz)
def _path(run_dir, name):
    for ext in (".csv", ".csv.gz"):
        p = os.path.join(run_dir, name + ext)
        if os.path.exists(p):
            return p
    return None


def read_csv(run_dir, name):
    """Read <run_dir>/<name>.csv (or .csv.gz); empty DataFrame if absent."""
    p = _path(run_dir, name)
    if p is None:
        return pd.DataFrame()
    try:
        return pd.read_csv(p)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def read_summary(run_dir):
    df = read_csv(run_dir, "summary")
    out = {}
    for k, v in zip(df["key"], df["value"]):
        try:
            out[k] = float(v)
        except (TypeError, ValueError):
            out[k] = v
    return out


def has_run(run_dir):
    return _path(run_dir, "summary") is not None


def parse_mbps(text):
    m = re.fullmatch(r"\s*([\d.]+)\s*([kMG]?)bps\s*", str(text))
    return float(m.group(1)) * {"k": 1e-3, "": 1e-6, "M": 1.0, "G": 1e3}[m.group(2)]


def parse_ms(text):
    m = re.fullmatch(r"\s*([\d.]+)\s*(ms|us|s)\s*", str(text))
    return float(m.group(1)) * {"ms": 1.0, "us": 1e-3, "s": 1e3}[m.group(2)]


def compress_run(run_dir):
    """gzip every .csv in a run directory (pandas reads .csv.gz transparently)."""
    for f in os.listdir(run_dir):
        if f.endswith(".csv"):
            src = os.path.join(run_dir, f)
            with open(src, "rb") as fi, gzip.open(src + ".gz", "wb", compresslevel=6) as fo:
                fo.write(fi.read())
            os.remove(src)


# ------------------------------------------------------------------ statistics helpers
def weighted_quantile(values, weights, q):
    values = np.asarray(values, dtype=float)
    weights = np.asarray(weights, dtype=float)
    if len(values) == 0 or weights.sum() <= 0:
        return float("nan")
    order = np.argsort(values)
    v, w = values[order], weights[order]
    cum = np.cumsum(w) - 0.5 * w
    return float(np.interp(q * w.sum(), cum, v))


def step_series(df, tcol, vcol, t0, t1):
    """Trace written only on change = step function. Return (values, durations) within [t0, t1]."""
    if df.empty:
        return np.array([]), np.array([])
    t = df[tcol].to_numpy(dtype=float)
    v = df[vcol].to_numpy(dtype=float)
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


_T975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306,
         9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131,
         20: 2.086, 30: 2.042}


def t_crit(df):
    """Two-sided 95% Student-t critical value."""
    if df < 1:
        return float("nan")
    for k in sorted(_T975):
        if df <= k:
            return _T975[k]
    return 1.96


def paired_ci(diffs):
    """Mean of paired differences and its 95% t-interval -> (mean, lo, hi, n)."""
    d = np.asarray([x for x in diffs if np.isfinite(x)], dtype=float)
    n = len(d)
    if n == 0:
        return float("nan"), float("nan"), float("nan"), 0
    mean = d.mean()
    if n < 2:
        return float(mean), float("nan"), float("nan"), n
    half = t_crit(n - 1) * d.std(ddof=1) / np.sqrt(n)
    return float(mean), float(mean - half), float(mean + half), n


# ------------------------------------------------------------------ detection metrics
def detection_metrics(run_dir, t0, t1, flow_starts):
    """See module docstring ('Detection'). Returns a dict (NaN where undefined)."""
    nan = float("nan")
    out = {"first_warning_s": nan, "first_loss_s": nan, "warned_loss_frac": nan,
           "lead_median_s": nan, "loss_events_checked": 0.0}
    st = read_csv(run_dir, "cong_state")
    ev = read_csv(run_dir, "rtt_trend_events")
    first_w, first_l, leads, warned, checked = [], [], [], 0, 0
    for f, start in enumerate(flow_starts):
        loss = np.sort(st[(st.flow == f) & st.new_state.isin(LOSS_STATES)].time_s.to_numpy()) if not st.empty else np.array([])
        # merge RECOVERY->LOSS pairs that belong to the same incident (closer than 0.5 s)
        merged = []
        for t in loss:
            if not merged or t - merged[-1] > 0.5:
                merged.append(t)
        loss = np.array(merged)
        warn = np.array([])
        if not ev.empty:
            e = ev[(ev.flow == f) & (((ev.new_state == "EARLY_CONGESTION") & (ev.reason == "rtt_trend")) |
                                     ((ev.new_state == "CONGESTED") & (ev.reason == "queue_delay")))]
            warn = np.sort(e.time_s.to_numpy())
        if len(loss):
            first_l.append(loss[0] - start)
        if len(warn):
            first_w.append(warn[0] - start)
        for i, tl in enumerate(loss):
            if tl < t0 or tl > t1:
                continue
            prev = loss[i - 1] if i > 0 else start
            cands = warn[(warn > prev) & (warn < tl)]
            checked += 1
            if len(cands):
                warned += 1
                leads.append(tl - cands[0])
    out["first_warning_s"] = float(np.mean(first_w)) if first_w else nan
    out["first_loss_s"] = float(np.mean(first_l)) if first_l else nan
    out["loss_events_checked"] = float(checked)
    if checked:
        out["warned_loss_frac"] = warned / checked
    if leads:
        out["lead_median_s"] = float(np.median(leads))
    return out


# ------------------------------------------------------------------ per-run metrics
def metrics_for_run(run_dir, warmup=10.0):
    s = read_summary(run_dir)
    T = float(s["param.simTime"])
    n_flows = int(s["param.nFlows"])
    seg = float(s["param.segmentSize"])
    bw = parse_mbps(s["param.bottleneckBw"])
    t0, t1 = float(warmup), T
    m = {"variant": s["param.tcpVariant"], "n_flows": n_flows, "sim_time": T, "warmup": t0}

    rtt = read_csv(run_dir, "rtt")
    r = rtt[(rtt.time_s >= t0) & (rtt.time_s <= t1)] if not rtt.empty else rtt
    if r.empty:
        for k in ("rtt_mean_ms", "rtt_median_ms", "rtt_p95_ms", "rtt_max_ms", "rtt_std_ms",
                  "rtt_slope_abs_mean"):
            m[k] = float("nan")
    else:
        m["rtt_mean_ms"] = float(r.rtt_ms.mean())
        m["rtt_median_ms"] = float(r.rtt_ms.median())
        m["rtt_p95_ms"] = float(r.rtt_ms.quantile(0.95))
        m["rtt_max_ms"] = float(r.rtt_ms.max())
        m["rtt_std_ms"] = float(r.rtt_ms.std())
        slopes = []
        for _, g in r.groupby("flow"):
            bins = np.floor(g.time_s.to_numpy() - t0).astype(int)
            for b in np.unique(bins):
                sel = bins == b
                if sel.sum() >= 10:
                    slopes.append(ols_slope(g.time_s.to_numpy()[sel], g.rtt_ms.to_numpy()[sel]))
        slopes = np.array([x for x in slopes if np.isfinite(x)])
        m["rtt_slope_abs_mean"] = float(np.abs(slopes).mean()) if len(slopes) else float("nan")

    qd = read_csv(run_dir, "queue_delay")
    q = qd[(qd.time_s >= t0) & (qd.time_s <= t1)] if not qd.empty else qd
    m["qdelay_mean_ms"] = float(q.sojourn_ms.mean()) if not q.empty else float("nan")
    m["qdelay_p95_ms"] = float(q.sojourn_ms.quantile(0.95)) if not q.empty else float("nan")

    vals, dur = step_series(read_csv(run_dir, "queue"), "time_s", "queue_packets", t0, t1)
    m["queue_mean_pkts"] = float(np.average(vals, weights=dur)) if dur.sum() > 0 else float("nan")
    m["queue_p95_pkts"] = weighted_quantile(vals, dur, 0.95)
    m["queue_max_pkts"] = float(vals.max()) if len(vals) else float("nan")

    tp = read_csv(run_dir, "throughput")
    w = tp[(tp.time_s > t0) & (tp.time_s <= t1)] if not tp.empty else tp
    if w.empty:
        m["goodput_mbps"] = m["utilization_pct"] = m["fairness_jain"] = float("nan")
    else:
        m["goodput_mbps"] = float(w.groupby("time_s").goodput_mbps.sum().mean())
        m["utilization_pct"] = 100.0 * m["goodput_mbps"] / (bw * seg / (seg + 52.0))
        m["fairness_jain"] = jain_index(w.groupby("flow").goodput_mbps.mean().to_numpy())

    drops = read_csv(run_dir, "drops")
    m["drops_total"] = float(s["bottleneck.dropped_packets"])
    m["drops_window"] = float(((drops.time_s >= t0) & (drops.time_s <= t1)).sum()) if not drops.empty else 0.0
    m["loss_rate_pct"] = float(s["bottleneck.drop_rate_percent"])
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

    cw = read_csv(run_dir, "cwnd")
    means, maxima = [], []
    for _, g in cw.groupby("flow"):
        vals, dur = step_series(g, "time_s", "cwnd_bytes", t0, t1)
        if dur.sum() > 0:
            means.append(np.average(vals, weights=dur) / seg)
            maxima.append(vals.max() / seg)
    m["cwnd_mean_segs"] = float(np.mean(means)) if means else float("nan")
    m["cwnd_max_segs"] = float(np.max(maxima)) if maxima else float("nan")

    trend = read_csv(run_dir, "rtt_trend")
    if trend.empty:
        m["frac_early"] = m["frac_congested"] = m["early_entries"] = m["delay_congested_entries"] = float("nan")
    else:
        fe, fc = [], []
        for _, g in trend.groupby("flow"):
            t = g.time_s.to_numpy()
            d = np.diff(np.concatenate([t, [t1]]))
            sel = (t >= t0) & (t <= t1)
            if d[sel].sum() > 0:
                stt = g.state.to_numpy()[sel]
                fe.append(d[sel][stt == "EARLY_CONGESTION"].sum() / d[sel].sum())
                fc.append(d[sel][stt == "CONGESTED"].sum() / d[sel].sum())
        m["frac_early"] = float(np.mean(fe)) if fe else float("nan")
        m["frac_congested"] = float(np.mean(fc)) if fc else float("nan")
        ev = read_csv(run_dir, "rtt_trend_events")
        if ev.empty:
            m["early_entries"] = m["delay_congested_entries"] = 0.0
        else:
            ev = ev[(ev.time_s >= t0) & (ev.time_s <= t1)]
            m["early_entries"] = float(((ev.new_state == "EARLY_CONGESTION") & (ev.reason == "rtt_trend")).sum())
            m["delay_congested_entries"] = float(((ev.new_state == "CONGESTED") & (ev.reason == "queue_delay")).sum())

    starts = [float(s[f"flow{i}.start_time_s"]) for i in range(n_flows)]
    m.update(detection_metrics(run_dir, t0, t1, starts))
    if trend.empty:  # baseline: no detector was running, so detection metrics are undefined
        m["warned_loss_frac"] = m["lead_median_s"] = m["first_warning_s"] = float("nan")
    return m
