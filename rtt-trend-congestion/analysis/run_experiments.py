#!/usr/bin/env python3
"""
run_experiments.py -- batch driver for the NS-3 simulation (rtt-baseline).

Run from the ns-3 root directory AFTER './ns3 build':

  python3 analysis/run_experiments.py --suite main        --runs 5 --out results/exp_main
  python3 analysis/run_experiments.py --suite sensitivity --runs 3 --out results/exp_sens
  python3 analysis/run_experiments.py --suite tuning      --out results/exp_tuning

Suites
  main         9 load scenarios (nFlows in {1,2,4} x bottleneck queue in {50,100,200} packets)
               x {baseline TcpNewReno, proposed TcpRttTrend} x RUNS replications (run = 1..RUNS).
  sensitivity  one scenario (2 flows, queue 100), baseline + proposed with ONE parameter changed
               at a time, RUNS replications each.
  tuning       small grid of parameter combinations on run numbers 101.. (kept disjoint from the
               evaluation runs 1..RUNS) -- used only to choose the default parameters.

Result layout:  <out>/<scenario>/<label>/run<k>/*.csv
Already finished runs (summary.csv present) are skipped, so the script can be re-started.
"""
import argparse
import itertools
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

SIM_TIME = 60
LOADS = [1, 2, 4]            # number of competing TCP flows
QUEUES = [50, 100, 200]      # bottleneck buffer [packets]
ALGOS = {"baseline": ["--tcpVariant=TcpNewReno"], "proposed": ["--tcpVariant=TcpRttTrend"]}


def scenario_args(n_flows, queue):
    return [f"--nFlows={n_flows}", f"--queuePackets={queue}", f"--simTime={SIM_TIME}"]


def suite_main(runs):
    jobs = []
    for n, q in itertools.product(LOADS, QUEUES):
        for algo, a in ALGOS.items():
            for run in range(1, runs + 1):
                jobs.append((f"n{n}_q{q}/{algo}/run{run}", scenario_args(n, q) + a + [f"--run={run}"]))
    return jobs


SENS_VALUES = {
    "slopeEnter": [1, 2, 3, 5, 8],
    "growthReduction": [0.25, 0.5, 0.75, 1.0],
    "congDelayMs": [30, 40, 60, 80, 120],
    "rttWindow": [8, 15, 25, 40],
    "persistTime": [0.2, 0.5, 1.0],
    "rttAlpha": [0.25, 0.5, 1.0],
    "congestedDecrease": [0, 0.05, 0.1, 0.2],
}


def suite_sensitivity(runs):
    jobs = []
    sc = scenario_args(2, 100)
    for run in range(1, runs + 1):
        jobs.append((f"n2_q100/baseline/run{run}", sc + ALGOS["baseline"] + [f"--run={run}"]))
        jobs.append((f"n2_q100/default/run{run}", sc + ALGOS["proposed"] + [f"--run={run}"]))
        for p, values in SENS_VALUES.items():
            for v in values:
                jobs.append((f"n2_q100/{p}={v}/run{run}",
                             sc + ALGOS["proposed"] + [f"--{p}={v}", f"--run={run}"]))
    return jobs


def suite_tuning(runs):
    jobs = []
    for n, q in [(1, 100), (4, 100)]:
        for run in (101, 102):
            jobs.append((f"n{n}_q{q}/baseline/run{run}", scenario_args(n, q) + ALGOS["baseline"] + [f"--run={run}"]))
            for cd, pt, w in itertools.product([40, 60, 80], [0.3, 0.5], [10, 15]):
                label = f"cd{cd}_pt{pt}_w{w}"
                jobs.append((f"n{n}_q{q}/{label}/run{run}",
                             scenario_args(n, q) + ALGOS["proposed"] +
                             [f"--congDelayMs={cd}", f"--persistTime={pt}", f"--rttWindow={w}", f"--run={run}"]))
    return jobs


def run_job(ns3_dir, out, rel, args, extra, force):
    out_dir = os.path.join(out, rel)
    if not force and os.path.exists(os.path.join(ns3_dir, out_dir, "summary.csv")):
        return rel, 0, "skipped"
    cmd_str = " ".join(["rtt-baseline"] + args + extra + [f"--outDir={out_dir}"])
    t = time.time()
    p = subprocess.run(["./ns3", "run", "--no-build", cmd_str], cwd=ns3_dir,
                       capture_output=True, text=True)
    return rel, p.returncode, f"{time.time() - t:.1f}s" if p.returncode == 0 else p.stderr[-300:]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--suite", choices=["main", "sensitivity", "tuning"], required=True)
    ap.add_argument("--runs", type=int, default=5, help="replications per configuration (run=1..RUNS)")
    ap.add_argument("--out", required=True, help="output root, relative to the ns-3 directory")
    ap.add_argument("--ns3-dir", default=".", help="ns-3 root directory (default: current)")
    ap.add_argument("--jobs", type=int, default=1, help="parallel simulations")
    ap.add_argument("--force", action="store_true", help="re-run even if results exist")
    ap.add_argument("--extra", nargs="*", default=[],
                    help="extra rtt-baseline arguments appended to EVERY run, e.g. --extra --simTime=30")
    a = ap.parse_args()

    jobs = {"main": suite_main, "sensitivity": suite_sensitivity, "tuning": suite_tuning}[a.suite](a.runs)
    print(f"{len(jobs)} simulations -> {a.out}  (parallel jobs: {a.jobs})")
    failed = 0
    with ThreadPoolExecutor(max_workers=a.jobs) as ex:
        futs = [ex.submit(run_job, a.ns3_dir, a.out, rel, args, a.extra, a.force) for rel, args in jobs]
        for i, f in enumerate(as_completed(futs), 1):
            rel, rc, info = f.result()
            if rc != 0:
                failed += 1
            print(f"[{i}/{len(jobs)}] {'OK  ' if rc == 0 else 'FAIL'} {rel} {info}", flush=True)
    print(f"finished, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
