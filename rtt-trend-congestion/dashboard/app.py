"""
Streamlit dashboard -- RTT Trend-Based Early Congestion Avoidance.

    streamlit run dashboard/app.py

Reads only files produced by the simulation pipeline:
  data/processed/<suite>/metrics_per_run.csv   metrics of every run
  data/raw/<suite>/<scenario>/<algo>/run1/     kept raw traces (time-series graphs)
  configs/<suite>.json                         scenario descriptions
Nothing is simulated or typed in here.
"""
import json
import os
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "analysis"))
import analyze as A  # noqa: E402
import interpret  # noqa: E402
import metrics as M  # noqa: E402
import plotting as P  # noqa: E402

DATA = os.environ.get("RTT_DATA_DIR", os.path.join(ROOT, "data"))
ALGO_ORDER = ["baseline", "proposed", "noslope", "monitor"]
ALGO_HELP = {"baseline": "Baseline TCP (NewReno)", "proposed": "RTT Trend-Based TCP (proposed)",
             "noslope": "Ablation: delay threshold only", "monitor": "Baseline + detector observing"}

st.set_page_config(page_title="RTT Trend-Based Early Congestion Avoidance", layout="wide")


@st.cache_data
def load_suite(suite):
    cfg = json.load(open(os.path.join(ROOT, "configs", f"{suite}.json")))
    df = pd.read_csv(os.path.join(DATA, "processed", suite, "metrics_per_run.csv"))
    scenarios = [s for s in cfg["scenarios"] if s in set(df.scenario)]
    summary = A.summarize(df)
    paired = A.paired_table(df, scenarios) if cfg["type"] == "comparison" else pd.DataFrame()
    return cfg, df, scenarios, summary, paired


def show(fig):
    st.pyplot(fig)
    plt.close(fig)


st.title("RTT Trend-Based Early Congestion Avoidance")
st.caption("NS-3 simulation study: baseline TCP NewReno vs an RTT-trend-based early congestion avoidance algorithm. "
           "All numbers on this page are read from simulation output.")

main_csv = os.path.join(DATA, "processed", "main", "metrics_per_run.csv")
if not os.path.exists(main_csv):
    st.error("No results found. Run the experiments first:\n\n"
             "`python3 experiments/run_experiments.py --config configs/main.json`  then  "
             "`python3 analysis/analyze.py --config configs/main.json`")
    st.stop()

cfg, df, scenarios, summary, paired = load_suite("main")
raw_root = os.path.join(DATA, "raw", "main")

# ------------------------------------------------------------------ sidebar
st.sidebar.header("Selection")
scen = st.sidebar.selectbox("Scenario", scenarios, format_func=lambda s: f"{s}")
avail = [a for a in ALGO_ORDER if a in cfg["algorithms"]]
algos = st.sidebar.multiselect("Algorithms to display", avail, default=["baseline", "proposed"],
                               format_func=lambda a: ALGO_HELP.get(a, a))
if not algos:
    st.warning("Select at least one algorithm in the sidebar.")
    st.stop()
sc_cfg = cfg["scenarios"][scen]
params = {**cfg["common"], **sc_cfg.get("params", {})}
n_flows = int(params["nFlows"])
flow = st.sidebar.selectbox("Flow shown in per-flow graphs", list(range(n_flows)), index=0)
runs = {a: os.path.join(raw_root, scen, a, "run1") for a in algos}
runs = {a: d for a, d in runs.items() if M.has_run(d)}
st.sidebar.caption("Time-series graphs show run 1 (raw traces of further runs are not kept). "
                   "Metric tables aggregate all runs.")
st.sidebar.markdown("**Scenario**  \n" + sc_cfg["description"])

tab_main, tab_all, tab_sens, tab_def = st.tabs(["Scenario view", "All scenarios", "Parameter sensitivity", "Definitions"])

# ------------------------------------------------------------------ scenario view
with tab_main:
    st.subheader("Simulation configuration")
    c = st.columns(6)
    c[0].metric("Bottleneck bandwidth", params["bottleneckBw"])
    c[1].metric("Bottleneck delay (one way)", params["bottleneckDelay"])
    c[2].metric("Queue size", f"{params['queuePackets']} packets")
    c[3].metric("Traffic", f"{n_flows} flow(s) x {params['appRate']}")
    c[4].metric("Duration", f"{params['simTime']} s")
    c[5].metric("Runs per algorithm", int(summary[summary.scenario == scen].runs.max()))
    base_rtt = 2 * (2 * M.parse_ms(params["accessDelay"]) + M.parse_ms(params["bottleneckDelay"]))
    st.caption(f"Propagation RTT = 2 x (2 x {params['accessDelay']} + {params['bottleneckDelay']}) = {base_rtt:g} ms. "
               f"Staggered start: {params['flowStagger']} s between flows, random start jitter up to {params['startJitter']} s.")

    st.subheader("Baseline vs proposed: summary metrics")
    S = summary[summary.scenario == scen].set_index("algo")
    ROWS = [("rtt_mean_ms", "Average RTT [ms]", 1), ("rtt_median_ms", "Median RTT [ms]", 1),
            ("rtt_p95_ms", "95th percentile RTT [ms]", 1), ("rtt_max_ms", "Maximum RTT [ms]", 1),
            ("goodput_mbps", "Throughput (goodput) [Mbit/s]", 2), ("loss_rate_pct", "Packet loss rate, whole run [%]", 3),
            ("drops_total", "Packets dropped, whole run", 1), ("retx_total", "Retransmitted segments, whole run", 1),
            ("cwnd_mean_segs", "Average cwnd [segments]", 1), ("cwnd_max_segs", "Maximum cwnd [segments]", 1),
            ("queue_mean_pkts", "Average queue [packets]", 1), ("fairness_jain", "Jain fairness index", 3)]
    table = {}
    for a in [x for x in ALGO_ORDER if x in algos and x in S.index]:
        table[ALGO_HELP[a]] = [f"{S.loc[a, k + '_mean']:.{d}f} +- {S.loc[a, k + '_std']:.{d}f}" for k, _, d in ROWS]
    t = pd.DataFrame(table, index=[r[1] for r in ROWS])
    if "baseline" in algos and "proposed" in algos and not paired.empty:
        ch = []
        for k, _, d in ROWS:
            r = paired[(paired.scenario == scen) & (paired.comparison == "proposed-baseline") & (paired.metric == k)]
            if r.empty:
                ch.append("")
                continue
            r = r.iloc[0]
            clear = np.isfinite(r.ci95_lo) and not (r.ci95_lo <= 0 <= r.ci95_hi)
            ch.append(f"{r.rel_change_pct:+.1f}% ({'CI excludes 0' if clear else 'no clear difference'})")
        t["Proposed vs baseline (paired)"] = ch
    st.dataframe(t)
    st.caption("mean +- standard deviation over runs, steady-state window after warm-up "
               f"({sc_cfg.get('warmup', cfg.get('warmup', 10))} s); drops/retransmissions marked 'whole run' include start-up.")

    if not runs:
        st.warning("Raw traces for the selected algorithms are not available (only metrics).")
    else:
        g1, g2 = st.tabs(["RTT and trend", "cwnd, throughput, loss, queue"])
        ttl = f"({scen}, run 1)"
        with g1:
            show(P.fig_rtt(runs, flow, f"{ttl}, flow {flow}"))
            det = {a: d for a, d in runs.items() if a in ("monitor", "proposed", "noslope")}
            if det:
                show(P.fig_trend(det, flow, f"{ttl}, flow {flow}"))
            else:
                st.info("Select 'proposed', 'noslope' or 'monitor' in the sidebar to see smoothed RTT, slope and state.")
        with g2:
            show(P.fig_cwnd(runs, flow, f"{ttl}, flow {flow}"))
            show(P.fig_throughput_loss(runs, ttl))
            show(P.fig_queue(runs, ttl))

    st.subheader("Interpretation (generated from the numbers above)")
    if paired.empty:
        st.info("No paired comparison available.")
    else:
        for line in interpret.describe(paired, scen) + interpret.observations(paired, summary, scen):
            st.markdown(f"- {line}")
        st.caption("Wording rule: 'lower/higher' appears only when the 95% interval of the paired difference "
                   "excludes zero. Runs differ only in random flow start times, so intervals describe sensitivity to "
                   "start-time phase, not variability of real networks.")

# ------------------------------------------------------------------ all scenarios
with tab_all:
    st.subheader("Scenario-level comparison")
    sel = st.multiselect("Algorithms", ["baseline", "proposed", "noslope"], default=["baseline", "proposed", "noslope"])
    if sel:
        show(P.fig_summary_bars(summary, scenarios, A.BAR_KEYS, tuple(sel)))
    st.markdown("**Paired differences (proposed - baseline) with 95% intervals**")
    show(P.fig_paired(paired, scenarios, A.PAIR_KEYS))
    st.markdown("**Delay / utilisation trade-off**")
    show(P.fig_tradeoff(summary, scenarios))
    if "monitor" in summary.algo.unique():
        st.markdown("**Early-warning behaviour (monitor-only runs)**")
        show(P.fig_detection(summary, scenarios))
    pt = paired[(paired.comparison == "proposed-baseline") & paired.metric.isin(A.PAIR_KEYS)]
    st.markdown("**Verdict tally over all scenario x metric pairs**")
    st.dataframe(pt.verdict.value_counts().rename_axis("verdict").reset_index(name="count"))

# ------------------------------------------------------------------ sensitivity
with tab_sens:
    sens_csv = os.path.join(DATA, "processed", "sensitivity", "metrics_per_run.csv")
    if not os.path.exists(sens_csv):
        st.info("Run `python3 experiments/run_experiments.py --config configs/sensitivity.json` to enable this tab.")
    else:
        scfg, sdf, sscen, ssum, _ = load_suite("sensitivity")
        s_pick = st.selectbox("Scenario", sscen, key="sens_scen")
        st.caption(scfg["scenarios"][s_pick]["description"])
        show(P.fig_sensitivity(ssum, s_pick))

# ------------------------------------------------------------------ definitions
with tab_def:
    st.markdown("```\n" + M.__doc__.strip() + "\n```")
