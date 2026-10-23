# RTT-Trend-Based Congestion Avoidance Simulation

A network-simulation project that explores whether trends in TCP
Round-Trip Time (RTT) can help identify developing congestion and adjust
congestion-window growth before severe queue buildup or packet loss
occurs.

The project uses **C++ and ns-3** for network simulation and **Python**
for analysis and graph generation. It compares a baseline TCP NewReno
run with a custom `TcpRttTrend` congestion-control variant.

> **Status:** This repository contains the project source and analysis
> scripts. It does not bundle ns-3 itself. The project must be built
> against a compatible ns-3 version. Exact build compatibility has not
> been verified across all ns-3 releases.

## Contents

``` text
.
├── rtt-baseline/
│   ├── rtt-baseline.cc       # Simulation entry point and command-line options
│   ├── sim-config.h          # Default topology, TCP, algorithm and output settings
│   ├── tcp-rtt-trend.cc      # RTT-trend congestion-control implementation
│   ├── tcp-rtt-trend.h       # Custom TCP variant declaration
│   ├── topology.cc/.h        # Dumbbell topology and bottleneck queue
│   ├── traffic.cc/.h         # TCP applications and flow setup
│   └── tracing.cc/.h         # CSV measurements and summary output
└── analysis/
    ├── plot_baseline.py      # Baseline overview graph and checks
    ├── plot_trend_run.py    # Detailed RTT-trend run plots
    ├── run_experiments.py   # Batch experiment driver
    ├── analyze_experiments.py
    ├── analyze_sensitivity.py
    └── common_metrics.py
```

## Project objective

When offered traffic exceeds a bottleneck link's capacity, packets
accumulate in the router queue. This can increase RTT and eventually
cause packet drops. The project investigates an RTT-trend-based response
that may detect developing congestion earlier than a response based only
on packet loss.

The proposed algorithm samples RTT, smooths per-RTT measurements with an
Exponentially Weighted Moving Average (EWMA), estimates the RTT trend
with a regression window, and uses congestion states to control
congestion-window growth.

The algorithm has three states:

-   `NORMAL`: normal congestion-window behaviour.
-   `EARLY_CONGESTION`: reduce or freeze additive congestion-window
    growth according to the configured parameter.
-   `CONGESTED`: apply a configured congestion-window reduction when the
    delay condition is met.

The implementation also uses persistence checks and hysteresis to avoid
reacting to every short-lived fluctuation.

## Technology stack

-   C++ (ns-3 simulation and TCP variant)
-   ns-3 Network Simulator
-   Python 3
-   pandas, NumPy and Matplotlib (analysis and plots)

## Default simulation configuration

The defaults are defined in `rtt-baseline/sim-config.h`.

  Setting                                                 Default
  ---------------------------------------- ----------------------
  Simulation duration                                  60 seconds
  Topology                                               Dumbbell
  Bottleneck bandwidth                                    10 Mbps
  Bottleneck one-way delay                                  20 ms
  Access-link bandwidth                                  100 Mbps
  Access-link one-way delay                  2 ms per access link
  Bottleneck queue                                    100 packets
  Number of flows                                               1
  Baseline TCP                                       `TcpNewReno`
  Proposed TCP                                      `TcpRttTrend`
  RTT regression window                        15 per-RTT samples
  EWMA alpha                                                  0.5
  Early-congestion slope entry threshold                   3 ms/s
  Early-congestion slope exit threshold                    1 ms/s
  Congestion queue-delay threshold                          40 ms

These are experimental defaults, not a guarantee that the proposed
algorithm outperforms NewReno. Compare both variants under identical
settings and report the measured results.

## Setup

### 1. Install ns-3

Download an ns-3 release from the [official ns-3
website](https://www.nsnam.org/). Use a release compatible with the APIs
used by the project. The custom TCP class may require adjustments for
different ns-3 releases.

On Ubuntu or Ubuntu under Windows Subsystem for Linux (WSL), install
build tools:

``` bash
sudo apt update
sudo apt install -y git g++ cmake ninja-build python3 python3-pip python3-venv pkg-config
```

Configure and build the ns-3 source tree according to the instructions
shipped with that ns-3 release. For releases using the `./ns3` wrapper,
the common commands are:

``` bash
./ns3 configure --enable-examples --enable-tests
./ns3 build
```

These commands build ns-3 itself; they do not automatically integrate
this project.

### 2. Integrate this project into ns-3

Copy the files inside this repository's `rtt-baseline/` directory into a
new directory under the ns-3 source tree, for example:

``` text
ns-3-dev/
└── scratch/
    └── rtt-baseline/
        ├── rtt-baseline.cc
        ├── sim-config.h
        ├── tcp-rtt-trend.cc
        ├── tcp-rtt-trend.h
        ├── topology.cc
        ├── topology.h
        ├── traffic.cc
        ├── traffic.h
        ├── tracing.cc
        └── tracing.h
```

For ns-3 releases that support per-scratch-program CMake files, create
`scratch/rtt-baseline/CMakeLists.txt`:

``` cmake
build_exec(
    TARGET_NAME rtt-baseline
    SOURCE_FILES
        rtt-baseline.cc
        tcp-rtt-trend.cc
        topology.cc
        traffic.cc
        tracing.cc
    LIBRARIES_TO_LINK
        ${libcore}
        ${libnetwork}
        ${libinternet}
        ${libpoint-to-point}
        ${libapplications}
        ${libtraffic-control}
)
```

Some ns-3 releases or project layouts may require different build
integration. If compilation fails, check the ns-3 version and the first
compiler error. In particular, custom TCP congestion-control APIs can
change between releases.

Build from the **ns-3 root directory**:

``` bash
./ns3 build
```

### 3. Install Python dependencies

From the ns-3 root directory, create and activate a virtual environment:

``` bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install pandas numpy matplotlib
```

Copy this repository's `analysis/` directory into the ns-3 root
directory if it is not already there. The commands below assume that
`analysis/` is located at the ns-3 root.

## Run the simulations

Run these commands from the ns-3 root directory after the program has
built successfully.

### Baseline: TCP NewReno

``` bash
./ns3 run "rtt-baseline --simTime=20 --nFlows=1 --queuePackets=100 --tcpVariant=TcpNewReno --outDir=results/baseline"
```

### Proposed algorithm: TCP RTT Trend

``` bash
./ns3 run "rtt-baseline --simTime=20 --nFlows=1 --queuePackets=100 --tcpVariant=TcpRttTrend --outDir=results/proposed"
```

Both runs should use the same topology and traffic parameters for a fair
comparison. The commands use a shorter 20-second simulation for an
initial check; the default experiment suite uses 60 seconds.

## Generate plots

### Baseline overview

``` bash
python3 analysis/plot_baseline.py results/baseline
```

This writes `baseline_overview.png` inside the baseline results
directory and prints basic verification checks.

### Proposed algorithm detail

``` bash
python3 analysis/plot_trend_run.py results/proposed --flow 0
```

This writes `trend_run.png` inside the proposed run's results directory.
The detailed trend plot requires a run made with
`--tcpVariant=TcpRttTrend` and a non-empty `rtt_trend.csv`.

## Run experiment suites

The experiment driver runs repeated simulations and stores results in a
directory hierarchy. Run from the ns-3 root.

### Main comparison suite

Nine load scenarios are covered: 1, 2 or 4 flows, crossed with queues of
50, 100 or 200 packets. Each scenario compares NewReno and RTT Trend.

``` bash
python3 analysis/run_experiments.py --suite main --runs 5 --out results/exp_main
```

The main suite launches 9 scenarios × 2 algorithms × number of runs.
With `--runs 5`, that is 90 simulations.

### Sensitivity suite

``` bash
python3 analysis/run_experiments.py --suite sensitivity --runs 3 --out results/exp_sens
```

This varies one RTT-trend parameter at a time under a two-flow,
100-packet-queue scenario. It can take a long time because it runs many
configurations.

### Tuning suite

``` bash
python3 analysis/run_experiments.py --suite tuning --out results/exp_tuning
```

The tuning suite explores selected congestion-delay thresholds,
persistence times and RTT-window sizes. Use it for parameter
exploration, not as a substitute for final evaluation.

Useful options supported by the experiment driver include `--jobs` for
parallel simulations, `--force` to rerun completed outputs, and
`--ns3-dir` to specify the ns-3 root directory. Start with one or two
individual runs before launching a batch suite.

## Output files

Each simulation writes CSV files into its selected output directory.
Files include measurements such as:

-   `rtt.csv` --- RTT trace measurements
-   `cwnd.csv` --- congestion-window changes
-   `throughput.csv` --- receiver goodput samples
-   `queue.csv` --- bottleneck queue occupancy
-   `queue_delay.csv` --- estimated queueing delay
-   `drops.csv` --- packet-drop measurements
-   `cong_state.csv` --- TCP congestion-state transitions
-   `rtt_trend.csv` --- RTT samples, smoothed values, slope and custom
    algorithm state
-   `rtt_trend_events.csv` --- custom algorithm state events, where
    emitted
-   `summary.csv` --- run parameters and summary values

Some files may contain no rows for the baseline algorithm when they only
apply to the proposed variant.

## How to evaluate the results

Compare the two algorithms under the same simulation settings. Useful
metrics include:

-   **RTT and queueing delay:** whether the algorithm limits excessive
    delay.
-   **Queue occupancy and packet drops:** whether bottleneck buildup and
    overflow change.
-   **Goodput:** whether useful delivered data is maintained.
-   **Congestion window:** how each algorithm changes its sending
    behaviour.
-   **Repeatability:** run multiple independent replications and compare
    averages and variation.

Do not conclude that the proposed algorithm is better from a single
graph or run. RTT can also be affected by factors other than congestion,
and an overly aggressive response may reduce throughput. Discuss both
benefits and trade-offs.

## Troubleshooting

-   **`./ns3` not found:** run commands from the root of an extracted
    ns-3 source tree.
-   **Program target not found:** confirm that `rtt-baseline` is
    integrated under the ns-3 tree and that the build completed
    successfully.
-   **Compiler errors in TCP headers or method signatures:** check ns-3
    release compatibility with the custom TCP implementation.
-   **`rtt_trend.csv` is empty:** confirm that the run uses
    `--tcpVariant=TcpRttTrend`.
-   **Plot script reports missing CSV files:** verify the simulation
    completed and that the output directory passed to the script is
    correct.
-   **Long experiment runtime:** start with a single 20-second
    simulation; the full sensitivity and tuning suites run many
    simulations.

## Limitations

-   Simulation results depend on the ns-3 version, configuration, random
    seed and workload.
-   Results from the simulated dumbbell topology do not automatically
    generalize to every real network.
-   The proposed congestion-control method must be validated empirically
    against the baseline.
-   This repository contains source code and analysis scripts, not a
    bundled ns-3 installation or precomputed results.

## References

-   [ns-3 official website and documentation](https://www.nsnam.org/)
-   [ns-3 releases](https://www.nsnam.org/releases/)

## License

Add the license required by your course or project owner before
redistributing this repository. No license file was included in the
supplied project archive.
