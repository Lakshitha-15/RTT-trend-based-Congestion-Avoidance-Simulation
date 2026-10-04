/*
 * tracing.h
 * Data collection only. Hooks ns-3 "trace sources" and writes CSV files.
 * It never changes the behaviour of the simulation.
 */
#ifndef TRACING_H
#define TRACING_H

#include "sim-config.h"
#include "topology.h"
#include "traffic.h"

#include "ns3/core-module.h"
#include "ns3/internet-module.h"
#include "ns3/traffic-control-module.h"

#include <fstream>
#include <map>
#include <string>
#include <vector>

class BaselineTracer
{
  public:
    BaselineTracer(const SimConfig& cfg, const DumbbellTopology& topo, const TrafficSetup& traffic);

    // Call once before Simulator::Run(): connects queue traces and schedules socket-trace
    // connection + periodic throughput sampling.
    void Install();

    // Call once after Simulator::Run() (before Simulator::Destroy()): writes summary.csv.
    void Finalize();

  private:
    void ConnectSenderTraces(uint32_t flow);
    void SampleThroughput();
    uint32_t FlowFromContext(const std::string& context) const;
    void OpenCsv(std::ofstream& f, const std::string& name, const std::string& header);

    // ---- socket trace sinks (context = config path of the firing socket) ----
    void OnCwnd(std::string context, uint32_t oldV, uint32_t newV);
    void OnSsthresh(std::string context, uint32_t oldV, uint32_t newV);
    void OnRtt(std::string context, ns3::Time oldV, ns3::Time newV);
    void OnCongState(std::string context,
                     ns3::TcpSocketState::TcpCongState_t oldV,
                     ns3::TcpSocketState::TcpCongState_t newV);

    // ---- bottleneck queue trace sinks ----
    void OnQueuePackets(uint32_t oldV, uint32_t newV);
    void OnQueueSojourn(ns3::Time sojourn);
    void OnQueueDrop(ns3::Ptr<const ns3::QueueDiscItem> item);

    SimConfig m_cfg;
    DumbbellTopology m_topo;
    TrafficSetup m_traffic;

    std::map<uint32_t, uint32_t> m_nodeToFlow; // sender node id -> flow index
    std::vector<uint64_t> m_lastRxBytes;       // per flow, for throughput deltas
    uint64_t m_dropCount;

    std::ofstream m_cwndFile;
    std::ofstream m_ssthreshFile;
    std::ofstream m_rttFile;
    std::ofstream m_stateFile;
    std::ofstream m_queueFile;
    std::ofstream m_sojournFile;
    std::ofstream m_dropFile;
    std::ofstream m_tputFile;
};

#endif // TRACING_H
