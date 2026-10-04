/*
 * rtt-baseline.cc  --  PART 1: baseline TCP over a dumbbell, with CSV tracing.
 * (No RTT-trend algorithm yet.)
 *
 * This file only wires the four independent pieces together:
 *   sim-config.h  : parameters
 *   topology.*    : network
 *   traffic.*     : TCP + applications
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
