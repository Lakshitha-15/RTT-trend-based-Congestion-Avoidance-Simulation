# RTT Trend-Based Early Congestion Avoidance (NS-3 simulation study)

**Research question.** Can the *trend* of TCP round-trip time be used as an early congestion signal that reduces
queueing delay and packet loss while keeping reasonable throughput, compared with loss-based TCP NewReno?

This repository contains a simulation (NS-3.40, C++), a proposed congestion-control algorithm (`TcpRttTrend`),
an experiment framework, a statistical analysis pipeline (Python) and a Streamlit dashboard.
Everything reported below was **measured** from simulation output produced by the code in this repository.
The report separates *implementation facts*, *measured results*, *interpretation* and *expected behaviour*.

---------------------------------------------------------------------------------------------------------

## 1. Problem statement
Standard TCP (NewReno, CUBIC) learns that the network is congested from packet loss. Loss only happens after the
bottleneck buffer is already full. We study whether the *rate of increase of RTT*, which starts rising as soon as a
queue builds, can be used to slow the window growth earlier.

## 2. Motivation
Late congestion signals cost: (i) long queueing delay ("bufferbloat"), (ii) retransmissions and wasted capacity,
(iii) large window reductions after loss. An earlier, graded signal could, in principle, remove some of these costs.

## 3. Existing limitation
Loss-based AIMD *deliberately* fills the buffer: with one flow, cwnd grows until queue overflow, so average RTT is
RTT_0 + (a large fraction of the buffer drain time). Our baseline measurements confirm this (Section 13).

## 4. Proposed approach
Observe RTT during the connection; detect a *persistent upward trend*; when detected, stop (or slow) window
growth before the buffer overflows. The mechanism is a state machine NORMAL / EARLY_CONGESTION / CONGESTED
(Sections 8-10). The algorithm is deliberately simple (moving window, linear regression, thresholds), no machine learning.

## 5. System architecture
```
configs/*.json ──► experiments/run_experiments.py ──► NS-3 (ns3/rtt-baseline) ──► CSV traces
                                   │                                                  │
                                   └── analysis/metrics.py (per-run metrics) ◄────────┘
                                                │
                  data/processed/<suite>/metrics_per_run.csv
                                                │
        analysis/analyze.py ──► tables (data/processed) + figures (plots/)     dashboard/app.py (Streamlit)
        analysis/verify_consistency.py (logical checks)
```
| NS-3 source (`ns3/rtt-baseline/`) | Role |
|---|---|
| `sim-config.h` | all parameters and defaults |
| `topology.h/.cc` | dumbbell topology, bottleneck queue |
| `traffic.h/.cc` | **baseline TCP configuration** (variant selection, buffers) and applications |
| `tcp-rtt-trend.h/.cc` | **proposed algorithm** `TcpRttTrend` (derived from `TcpNewReno`) |
| `tracing.h/.cc` | all CSV tracing (RTT, cwnd, queue, drops, retransmissions, detector state) |
| `rtt-baseline.cc` | `main()`, command-line interface |

(The files stay in one directory because NS-3 builds a `scratch/` sub-directory as one executable.)

## 6. Network topology
Dumbbell: N senders -- access links (100 Mbit/s, 2 ms) -- router L == bottleneck (default 10 Mbit/s, 20 ms,
FIFO queue of 100 packets) == router R -- access links -- N receivers. Propagation RTT_0 = 2 (2 x 2 ms + 20 ms) = 48 ms.
Access queues are large (1000 packets), so the bottleneck queue is the only place where packets are dropped.
Traffic: NS-3 `OnOffApplication` in constant-rate mode over TCP (application rate is configurable per flow).

## 7. RTT measurement (implementation fact)
ns-3 stamps data segments with a TCP timestamp (1 ms resolution). When an ACK arrives, `TcpSocketBase::EstimateRtt`
computes a raw measurement, feeds it to the RFC 6298 estimator, and stores the **smoothed RTT**
`SRTT <- 7/8 SRTT + 1/8 m` in `m_lastRtt`. This SRTT is both what the `RTT` trace source reports (`rtt.csv`,
one row per ACK) and the only RTT value that a congestion-control class can see (`PktsAcked(tcb, segs, rtt)`).
`TcpRttTrend` therefore treats it as its input. It averages the values received during one round trip into a single
**per-RTT sample** `x_k`, so every flow contributes samples at the same rate regardless of its ACK rate.
Duplicate ACKs repeat the previous value and are ignored.

## 8. RTT trend detection
1. EWMA over per-RTT samples: `s_k = a x_k + (1-a) s_(k-1)` (a = 0.5). Purpose: suppress timestamp quantisation and ACK-timing noise.
2. Base RTT `b = min s_k` and queueing-delay estimate `q_k = s_k - b`.
3. Sliding window of the last W = 15 smoothed samples `(t_i, s_i)`; OLS slope
   `slope = sum (t_i - t_mean)(s_i - s_mean) / sum (t_i - t_mean)^2` [ms/s].
4. Persistence: the condition must hold continuously for `persistTime` (0.3 s).

## 9. Congestion state machine
| From | To | Condition |
|---|---|---|
| NORMAL | EARLY_CONGESTION | slope >= 3 ms/s and q >= 10 ms, continuously for 0.3 s |
| NORMAL, EARLY | CONGESTED | loss (NewReno enters Recovery/Loss) **or** q >= 40 ms |
| EARLY | NORMAL | q < 5 ms, or slope <= 1 ms/s continuously for 0.3 s |
| CONGESTED | EARLY | no loss active and q < 20 ms |

Hysteresis: separate entry/exit slope thresholds (3 vs 1 ms/s), exit delay thresholds at 50% of the entry thresholds, persistence timers.

## 10. Congestion response
* NORMAL: identical to NewReno (the code calls NewReno's function).
* EARLY_CONGESTION / CONGESTED: additive increase scaled by (1 - beta), beta = 1 (window frozen); slow start is ended (ssthresh <- cwnd).
* CONGESTED reached by delay (no loss yet): cwnd <- (1 - gamma) cwnd, gamma = 0.1, at most once per 4 smoothed RTTs, floor 4 segments.
* Losses are handled exactly as in NewReno.

## 11. Experimental methodology
* **Scenarios (11)** in `configs/main.json`: S01 light (1 flow, 4 Mbit/s), S02 moderate (2 x 4.5 Mbit/s),
  S03 heavy (4 saturating flows), S04 rapidly increasing load (6 flows x 3 Mbit/s starting 4 s apart),
  S05 reference (2 saturating flows), S06/S07 capacity 5 / 20 Mbit/s, S08/S09 queue 25 / 400 packets, S10/S11 bottleneck delay 5 / 50 ms.
  Each of S06-S11 changes exactly one parameter of S05.
* **Algorithms (4):** `baseline` (TcpNewReno), `proposed` (TcpRttTrend, defaults), `noslope` (ablation: slope trigger disabled, delay threshold only),
  `monitor` (detector running, response disabled; used for detection-time measurements).
* **Fair comparison:** within a scenario every algorithm gets identical topology, parameters, duration, seed and run number k = 1..5
  (the run number changes the random flow start times, jitter up to 1 s). `verify_consistency.py` checks this.
* **Duration** 60 s; metrics use the window after a warm-up (10 s; 5 s for S04).
* **Statistics:** per-metric paired difference over runs with the same k, 95% Student-t interval (n = 5).
  The text says "better/worse" only if the interval excludes zero.
* **Sensitivity:** `configs/sensitivity.json`: one parameter changed at a time on S01 and S05 (3 runs each).
* **Tuning disclosure:** default parameters came from a 12-combination grid on separate runs (101, 102) in two scenarios,
  ranked by RTT and loss (fairness was not a criterion). The evaluation uses runs 1..5.

## 12. Metrics (mathematical definitions)
Window [t0, T]; all values from simulation CSVs (`analysis/metrics.py` documents them in code).
* RTT mean / median / 95th percentile / maximum: statistics of all `rtt.csv` rows in the window (per-ACK SRTT).
* Queueing delay: same statistics over `queue_delay.csv` (per-packet sojourn time).
* RTT trend: mean over 1 s bins of |OLS slope of RTT vs time| [ms/s].
* Goodput G = mean over 0.1 s bins of the sum over flows of delivered bytes x 8 / 0.1 s; utilisation = G / (C x MSS/(MSS+52)).
* Packet loss rate = 100 x dropped / received packets at the bottleneck queue (whole run); steady-state drops counted in the window.
* Retransmissions: data segments whose sequence number was already sent; loss-recovery events: entries into CA_RECOVERY / CA_LOSS.
* cwnd: time-weighted mean of the step function (averaged over flows) and maximum, in segments.
* Queue: time-weighted mean / 95th percentile / maximum [packets].
* Fairness: Jain index J = (sum x)^2 / (n sum x^2) of per-flow goodput.
* Detection time (monitor runs): time from flow start to the first early warning (EARLY by trend or CONGESTED by delay), time to first loss,
  share of steady-state loss events preceded by a warning since the previous loss, and median lead time (loss time minus warning time).

## 13. Results (measured; 5 runs per cell, mean values)
Source: `data/processed/main/RESULTS.md`, `paired_differences.csv`, figures in `plots/main/`.
"n.s." = 95% interval of the paired difference contains zero.

| Scenario | Mean RTT [ms] | p95 RTT [ms] | Utilisation [%] | Loss-recovery events (steady) | Jain fairness |
|---|---|---|---|---|---|
| S01 light | 52.4 -> 52.4 | 52.5 -> 52.5 | 41.4 -> 41.4 | 0 -> 0 | 1.00 -> 1.00 |
| S02 moderate | 52.2 -> 52.2 | 52.4 -> 52.4 | 93.2 -> 93.2 | 0 -> 0 | 1.00 -> 1.00 |
| S03 heavy | 150.9 -> 140.0 (n.s.) | 175.1 -> 155.3 | 99.9 -> 99.9 | 32.0 -> 0.8 | 0.96 -> 0.53 (worse) |
| S04 ramp | 139.1 -> 83.4 | 177.8 -> 129.7 | 95.9 -> 95.9 | 62.2 -> 6.8 | 0.92 -> 0.85 (n.s.) |
| S05 reference | 145.1 -> 109.2 | 170.6 -> 122.6 | 99.9 -> 99.9 | 9.4 -> 0.0 | 0.97 -> 0.55 (worse) |
| S06 5 Mbit/s | 242.2 -> 191.0 | 292.7 -> 208.0 | 99.9 -> 99.9 | 5.8 -> 0.0 | 0.98 -> 0.59 (worse) |
| S07 20 Mbit/s | 92.9 -> 88.1 (n.s.) | 109.2 -> 105.5 | 99.9 -> 99.9 | 11.8 -> 0.4 | 0.97 -> 0.59 (worse) |
| S08 queue 25 | 70.0 -> 71.5 (worse) | 81.9 -> 82.5 (n.s.) | 98.8 -> 97.7 (worse) | 36.8 -> 14.0 | 0.98 -> 0.86 (n.s.) |
| S09 queue 400 | 476.9 -> 208.7 | 526.6 -> 240.8 | 99.7 -> 99.9 (n.s.) | 0.2 -> 0.0 (n.s.) | 0.60 -> 0.63 |
| S10 delay 5 ms | 119.5 -> 91.0 | 140.8 -> 101.5 | 99.9 -> 99.9 | 12.2 -> 0.0 | 0.96 -> 0.56 (worse) |
| S11 delay 50 ms | 191.5 -> 148.8 | 229.5 -> 162.0 | 99.9 -> 99.9 | 4.8 -> 0.0 | 0.98 -> 0.58 (worse) |

Tally over the 11 scenarios (proposed vs baseline): mean RTT lower in 6, no clear difference in 4, higher in 1;
p95 RTT lower in 8, no clear difference in 3; utilisation no clear difference in 10, lower in 1;
steady-state loss-recovery events lower in 8, no clear difference in 3; fairness lower in 6, no clear difference in 4, higher in 1.

Other measured facts:
* **Start-up losses are not prevented.** Whole-run drops are similar in several scenarios (S05 102 -> 96, S07 130 -> 128, S11 118 -> 113 packets) because the slow-start overshoot happens before the detector has a full window.
* **Ablation.** Disabling the slope trigger (`noslope`) changes mean RTT by at most 3.4 ms in either direction
  (no clear difference in 7 of 11 scenarios; proposed 2.1% (2.9 ms) lower in S03; proposed 3.4, 1.0 and 1.0 ms higher in S08, S10, S11),
  although in the sensitivity suite (S05) the share of time in EARLY_CONGESTION drops from 23% to 3%. In these experiments the RTT reduction is produced mainly by the
  queueing-delay threshold (CONGESTED) together with the freeze/decrease response, not by the slope trigger.
* **Detection (monitor-only runs).** In congested scenarios, 19-73% of steady-state loss events were preceded by a warning (S09: 0 of 0.2 events per run),
  median lead time 0.8-24.4 s. The first warning after a flow start came at 1.7-6.7 s, later than the first loss (0.35-1.6 s; S04: 5.6 s) in all congested scenarios,
  i.e. the first (slow-start) loss was never anticipated. The CONGESTED state is "sticky" with competing flows (70-92% of the time in eight of the nine congested scenarios; S08: 16%), because a standing queue keeps q above the exit threshold; this lowers the number of new warnings.
* **False alarms.** In the uncongested scenarios S01 and S02 there were no EARLY/CONGESTED entries at all, for every parameter value tested
  (slope 0.5-8 ms/s, minimum queue delay 0-20 ms). This is **not** evidence of noise robustness: RTT in these runs is almost perfectly flat (S01: 52.4 ms) because the simulation has no cross-traffic or jitter.
* **Sensitivity (S05, 3 runs).** Mean RTT vs `congDelayMs` 30 / 40 / 60 / 80 / 120 ms: 97.5 / 104.5 / 124.4 / 133.7 / 142.6 ms (baseline 142.5); Jain fairness 0.56 / 0.55 / 0.54 / 0.62 / 0.89.
  `slopeEnter` 0.5-8 ms/s, `rttWindow` 8-40, `persistTime` 0.2-1.0 s: mean RTT 104.3-105.8 ms. `congestedDecrease` 0: RTT 158.6 ms (above the baseline) and fairness 0.73;
  `growthReduction` 0.25: RTT 118.6 ms, fairness 0.72. Utilisation stayed 99.87% in all variants. The delay-threshold and response-strength parameters move RTT and fairness in opposite directions.

**Interpretation.** (a) Under saturating load the proposed algorithm lowers RTT and removes most steady-state loss events without a measurable utilisation loss, except with a very small buffer (S08), where utilisation is 1.1% lower and RTT slightly higher.
(b) With two or more competing flows it makes the allocation markedly less fair; in S05 run 1 the two flows obtained 0.44 and 9.2 Mbit/s (baseline 5.6 and 4.0), in S03 run 1 two flows obtained about 4.3 Mbit/s and two about 0.4-0.7 Mbit/s. A plausible mechanism is that freezing growth locks the existing window split, while AIMD's repeated decreases are what equalise flows; the data are consistent with this but it was not isolated experimentally.
(c) The benefit measured here comes mostly from the delay threshold, so "RTT trend" detection per se was not shown to be necessary in these scenarios.
(d) No claim of general superiority is made.

## 14. Limitations
Single dumbbell topology; long-lived or constant-rate flows only (no short flows, no reverse traffic, no UDP cross traffic); no RTT noise or jitter in the simulated network, so noise-induced false positives were not
exercised; replicates differ only in random flow start times (intervals measure sensitivity to start-time phase, not environmental variability); the algorithm sees only ns-3's smoothed RTT; per-flow base RTT (a late-starting flow behind a standing queue under-estimates queueing delay);
absolute-millisecond thresholds tuned on a small grid for a 10 Mbit/s path; fairness degradation; start-up not protected; cwnd is not limited for application-limited flows (S01 and S02 show a mean cwnd in the thousands of segments, S04 a maximum of about 1,800); RTT statistics weight each ACK equally; only NewReno was compared.

## 15. Future improvements
Relative thresholds (fractions of base RTT); robust base-RTT estimation; fairness-restoring decrease (proportional or randomised); raw per-ACK RTT samples through a custom RTT estimator; a slow-start exit rule based on per-round RTT growth;
noisy and mixed-traffic scenarios (UDP cross traffic, short flows); comparison with CUBIC, Vegas and BBR; confidence intervals from more independent random seeds.

## 16. Installation
```bash
# 1. ns-3.40 (Linux or WSL2 Ubuntu)
sudo apt install g++ python3 python3-pip cmake ninja-build
wget https://www.nsnam.org/releases/ns-allinone-3.40.tar.bz2 && tar xjf ns-allinone-3.40.tar.bz2
# 2. this project
cd rtt-trend-congestion
pip install -r requirements.txt
scripts/setup_ns3.sh ../ns-allinone-3.40/ns-3.40      # copies sources, configures, builds (several minutes)
export NS3_DIR=$(realpath ../ns-allinone-3.40/ns-3.40)
```
Tested on ns-3.40, Ubuntu 24.04, g++ 13.3, Python 3.12.

## 17. Running simulations
```bash
# single runs (from $NS3_DIR)
./ns3 run "rtt-baseline --outDir=/tmp/base"                                  # baseline NewReno
./ns3 run "rtt-baseline --tcpVariant=TcpRttTrend --outDir=/tmp/prop"         # proposed
# experiment suites (from the project root; roughly 10-15 min and 8-10 min on one core)
python3 experiments/run_experiments.py --config configs/main.json           # 11 scenarios x 4 algorithms x 5 runs
python3 experiments/run_experiments.py --config configs/sensitivity.json    # parameter sweeps
# options: --only S01_light S05_reference   --runs 2   --jobs 4   --keep-raw 99
```
The runner is resumable. It stores per-run metrics in `data/processed/<suite>/metrics_per_run.csv` and keeps gzip-compressed raw traces for run 1 only (`--keep-raw`).

## 18. Running analysis
```bash
python3 analysis/analyze.py --config configs/main.json          # tables, RESULTS.md, plots/main/
python3 analysis/analyze.py --config configs/sensitivity.json   # plots/sensitivity/
python3 analysis/verify_consistency.py --config configs/main.json   # logical checks (880 checks pass on the shipped data)
python3 analysis/plot_run.py <run_dir>                          # inspect one run of the proposed algorithm
```

## 19. Launching the dashboard
```bash
streamlit run dashboard/app.py
```
Select a scenario and algorithms in the sidebar; the page shows the configuration, summary metrics with paired comparison, RTT / smoothed RTT / slope / state graphs, cwnd, throughput, loss, queue, an automatically generated factual interpretation, all-scenario summaries and the sensitivity study.
