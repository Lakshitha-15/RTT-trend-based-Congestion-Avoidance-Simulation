
#!/usr/bin/env bash
# Copy the Part 2 C++ sources into ns-3.40, then configure and build.
# Usage: scripts/setup_ns3.sh /path/to/ns-3.40

set -euo pipefail

if [ $# -ne 1 ]; then
    echo "usage: $0 /path/to/ns-3.40"
    exit 1
fi

NS3_DIR="$(cd "$1" && pwd)"
HERE="$(cd "$(dirname "$0")/.." && pwd)"

if [ ! -x "$NS3_DIR/ns3" ]; then
    echo "$NS3_DIR does not look like an ns-3 tree: no executable ./ns3 script"
    exit 1
fi

if [ ! -d "$HERE/ns3/rtt-baseline" ]; then
    echo "ERROR: C++ source directory not found: $HERE/ns3/rtt-baseline"
    exit 1
fi

rm -rf "$NS3_DIR/scratch/rtt-baseline"
cp -r "$HERE/ns3/rtt-baseline" "$NS3_DIR/scratch/rtt-baseline"

cd "$NS3_DIR"

./ns3 configure \
    --build-profile=optimized \
    --disable-examples \
    --disable-tests \
    --enable-modules="core;network;internet;point-to-point;traffic-control;applications"

./ns3 build

echo
echo "Setup complete."
echo "NS-3 directory: $NS3_DIR"
echo "Next, run from the project folder:"
echo "export NS3_DIR=$NS3_DIR"
echo "python3 experiments/run_experiments.py --config configs/main.json"
