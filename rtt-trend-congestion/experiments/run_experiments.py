#!/usr/bin/env python3
"""
run_experiments.py -- config-driven batch runner for the NS-3 simulation.

  export NS3_DIR=/path/to/ns-3.40          # tree prepared with scripts/setup_ns3.sh
  python3 experiments/run_experiments.py --config configs/main.json
  python3 experiments/run_experiments.py --config configs/sensitivity.json
  python3 experiments/run_experiments.py --config configs/main.json --only S01_light S03_heavy --runs 2

For every scenario x algorithm x run k it executes
    rtt-baseline <scenario parameters> <algorithm parameters> --seed=<seed> --run=k --outDir=...
All algorithms of one scenario receive IDENTICAL scenario parameters, seed and run number, so
topology, traffic, random start times and duration are the same; only the congestion control differs.

Data handling (keeps the repository small):
  1. the simulator writes full CSV traces to  data/raw/<suite>/<scenario>/<algo>/run<k>/
  2. metrics of the run are computed immediately and appended to
     data/processed/<suite>/metrics_per_run.csv       (one row per run, all runs kept)
  3. raw traces of run 1..--keep-raw are gzip-compressed and kept (used for time-series plots and
     the dashboard); raw traces of later runs are deleted. Use --keep-raw 99 to keep everything.
The script is resumable: runs already present in metrics_per_run.csv are skipped.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "analysis"))
import metrics  # noqa: E402

NON_SIM_KEYS = {"description", "sweep_param", "sweep_value", "category"}


def sim_args(scenario_params, common, algo_params, seed, run):
    p = {**common, **scenario_params, **algo_params}
    p = {k: v for k, v in p.items() if k not in NON_SIM_KEYS}
    p["seed"] = p.get("seed", seed)
    p["run"] = run
    return p


def run_simulation(ns3_dir, params, out_dir):
    args = " ".join([f"--{k}={v}" for k, v in params.items()] + [f"--outDir={out_dir}"])
    t = time.time()
    p = subprocess.run(["./ns3", "run", "--no-build", f"scratch/rtt-baseline/rtt-baseline {args}"], cwd=ns3_dir,
                       capture_output=True, text=True)
    return p.returncode, time.time() - t, p.stderr[-400:]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    ap.add_argument("--ns3-dir", default=os.environ.get("NS3_DIR"), help="ns-3 root (default: $NS3_DIR)")
    ap.add_argument("--runs", type=int, help="override number of runs per configuration")
    ap.add_argument("--only", nargs="*", help="only these scenario names")
    ap.add_argument("--algos", nargs="*", help="only these algorithm labels")
    ap.add_argument("--keep-raw", type=int, default=1, help="keep gzip'd raw traces of runs 1..N (default 1)")
    ap.add_argument("--jobs", type=int, default=1, help="parallel simulations")
    ap.add_argument("--data-dir", default=os.path.join(ROOT, "data"))
    a = ap.parse_args()
    if not a.ns3_dir or not os.path.exists(os.path.join(a.ns3_dir, "ns3")):
        sys.exit("Set --ns3-dir or $NS3_DIR to an ns-3 tree prepared with scripts/setup_ns3.sh")

    cfg = json.load(open(a.config))
    suite = cfg["name"]
    runs = a.runs or cfg["runs"]
    raw_root = os.path.abspath(os.path.join(a.data_dir, "raw", suite))
    proc_dir = os.path.join(a.data_dir, "processed", suite)
    os.makedirs(proc_dir, exist_ok=True)
    csv_path = os.path.join(proc_dir, "metrics_per_run.csv")
    done = pd.read_csv(csv_path) if os.path.exists(csv_path) else pd.DataFrame()
    done_keys = set(zip(done.scenario, done.algo, done.run)) if not done.empty else set()
    rows = done.to_dict("records") if not done.empty else []

    jobs = []
    for scen, sc in cfg["scenarios"].items():
        if a.only and scen not in a.only:
            continue
        for algo, ap_ in cfg["algorithms"].items():
            if a.algos and algo not in a.algos:
                continue
            for run in range(1, runs + 1):
                if (scen, algo, run) in done_keys:
                    continue
                params = sim_args(sc.get("params", {}), cfg["common"], ap_, cfg["common"].get("seed", 1), run)
                jobs.append((scen, algo, run, params, float(sc.get("warmup", cfg.get("warmup", 10)))))
    total = len(jobs)
    print(f"suite '{suite}': {total} simulations to run ({len(done_keys)} already done)")
    if not total:
        return

    def work(job):
        scen, algo, run, params, warmup = job
        out_dir = os.path.join(raw_root, scen, algo, f"run{run}")
        if os.path.exists(out_dir):
            shutil.rmtree(out_dir)
        rc, secs, err = run_simulation(a.ns3_dir, params, out_dir)
        return job, out_dir, rc, secs, err

    failed = 0
    with ThreadPoolExecutor(max_workers=a.jobs) as ex:
        futs = [ex.submit(work, j) for j in jobs]
        for i, f in enumerate(as_completed(futs), 1):
            (scen, algo, run, params, warmup), out_dir, rc, secs, err = f.result()
            tag = f"{scen}/{algo}/run{run}"
            if rc != 0:
                failed += 1
                print(f"[{i}/{total}] FAIL {tag}: {err}", flush=True)
                continue
            m = metrics.metrics_for_run(out_dir, warmup)
            m.update(scenario=scen, algo=algo, run=run)
            rows.append(m)
            pd.DataFrame(rows).to_csv(csv_path, index=False)
            if run <= a.keep_raw:
                metrics.compress_run(out_dir)
            else:
                shutil.rmtree(out_dir)
            print(f"[{i}/{total}] OK   {tag}  ({secs:.1f}s)", flush=True)
    print(f"finished, {failed} failed; metrics in {csv_path}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
