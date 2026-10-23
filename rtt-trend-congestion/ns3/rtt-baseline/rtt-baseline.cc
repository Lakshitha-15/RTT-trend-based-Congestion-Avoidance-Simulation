/*
 * rtt-baseline.cc  --  dumbbell experiment driver.
 * --tcpVariant=TcpNewReno (default) = baseline (PART 1);
 * --tcpVariant=TcpRttTrend           = proposed RTT-trend algorithm (PART 2).
 *
 * This file only wires the four independent pieces together:
 *   sim-config.h  : parameters
 *   topology.*    : network
 *   traffic.*     : TCP + applications
 *   tcp-rtt-trend.*: the proposed congestion-control algorithm (PART 2)
 *   tracing.*     : data collection
 */
#include "sim-config.h"
#include "topology.h"
#include "tracing.h"
#include "traffic.h"

#include "ns3/core-module.h"

#include <filesystem>

using namespace ns3;

int
main(int argc, char* argv[])
{
    SimConfig cfg;

    CommandLine cmd(__FILE__);
    cmd.AddValue("simTime", "Simulation duration [s]", cfg.simTime);
    cmd.AddValue("seed", "RNG seed", cfg.seed);
    cmd.AddValue("run", "RNG run number", cfg.run);
    cmd.AddValue("bottleneckBw", "Bottleneck link rate, e.g. 10Mbps", cfg.bottleneckBw);
    cmd.AddValue("bottleneckDelay", "Bottleneck one-way delay, e.g. 20ms", cfg.bottleneckDelay);
    cmd.AddValue("accessBw", "Access link rate, e.g. 100Mbps", cfg.accessBw);
    cmd.AddValue("accessDelay", "Access link one-way delay (each), e.g. 2ms", cfg.accessDelay);
    cmd.AddValue("queuePackets", "Bottleneck queue size [packets]", cfg.queuePackets);
    cmd.AddValue("nFlows", "Number of TCP flows (sender/receiver pairs)", cfg.nFlows);
    cmd.AddValue("tcpVariant", "TCP variant TypeId name, e.g. TcpNewReno, TcpCubic", cfg.tcpVariant);
    cmd.AddValue("appRate", "Application offered rate per flow, e.g. 20Mbps", cfg.appRate);
    cmd.AddValue("segmentSize", "TCP segment size [bytes]", cfg.segmentSize);
    cmd.AddValue("appStart", "Start time of first flow [s]", cfg.appStart);
    cmd.AddValue("flowStagger", "Start offset between consecutive flows [s]", cfg.flowStagger);
    cmd.AddValue("startJitter", "Random start jitter upper bound [s]", cfg.startJitter);
    // PART 2 (only used with --tcpVariant=TcpRttTrend)
    cmd.AddValue("rttWindow", "RTT-trend: regression window [per-RTT samples]", cfg.rttWindow);
    cmd.AddValue("rttAlpha", "RTT-trend: EWMA gain in (0,1]", cfg.rttAlpha);
    cmd.AddValue("slopeEnter", "RTT-trend: slope to enter EARLY_CONGESTION [ms/s]", cfg.slopeEnter);
    cmd.AddValue("slopeExit", "RTT-trend: slope to leave EARLY_CONGESTION [ms/s]", cfg.slopeExit);
    cmd.AddValue("persistTime", "RTT-trend: persistence time [s]", cfg.persistTime);
    cmd.AddValue("minQueueDelayMs", "RTT-trend: ignore trends below this queue delay [ms]", cfg.minQueueDelayMs);
    cmd.AddValue("congDelayMs", "RTT-trend: queue delay meaning CONGESTED [ms]", cfg.congDelayMs);
    cmd.AddValue("exitFraction", "RTT-trend: hysteresis factor for delay exits", cfg.exitFraction);
    cmd.AddValue("growthReduction", "RTT-trend: beta, growth removed in EARLY (0..1)", cfg.growthReduction);
    cmd.AddValue("congestedDecrease", "RTT-trend: gamma, delay-triggered decrease (0..0.9)", cfg.congestedDecrease);
    cmd.AddValue("decreaseIntervalRtts", "RTT-trend: min spacing of decreases [RTTs]", cfg.decreaseIntervalRtts);
    cmd.AddValue("minCwndSegs", "RTT-trend: cwnd floor for own reductions [segments]", cfg.minCwndSegs);
    cmd.AddValue("maxCwndSegs", "RTT-trend: cwnd cap [segments], 0 = none", cfg.maxCwndSegs);
    cmd.AddValue("outDir", "Output directory for CSV files", cfg.outDir);
    cmd.AddValue("throughputInterval", "Goodput sampling interval [s]", cfg.throughputInterval);
    cmd.Parse(argc, argv);

    RngSeedManager::SetSeed(cfg.seed);
    RngSeedManager::SetRun(cfg.run);

    std::filesystem::create_directories(cfg.outDir);

    ConfigureTcpDefaults(cfg);                            // 1. TCP attribute defaults (before nodes!)
    DumbbellTopology topo = BuildDumbbellTopology(cfg);   // 2. network
    TrafficSetup traffic = InstallTraffic(cfg, topo);     // 3. applications
    BaselineTracer tracer(cfg, topo, traffic);            // 4. tracing
    tracer.Install();

    Simulator::Stop(Seconds(cfg.simTime));
    Simulator::Run();
    tracer.Finalize();
    Simulator::Destroy();

    NS_LOG_UNCOND("Simulation finished. CSV files written to: " << cfg.outDir);
    return 0;
}
