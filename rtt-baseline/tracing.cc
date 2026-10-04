#include "tracing.h"

#include "ns3/applications-module.h"

#include <iomanip>

using namespace ns3;

BaselineTracer::BaselineTracer(const SimConfig& cfg,
                               const DumbbellTopology& topo,
                               const TrafficSetup& traffic)
    : m_cfg(cfg),
      m_topo(topo),
      m_traffic(traffic),
      m_lastRxBytes(cfg.nFlows, 0),
      m_dropCount(0)
{
    for (uint32_t i = 0; i < cfg.nFlows; ++i)
    {
        m_nodeToFlow[topo.senders.Get(i)->GetId()] = i;
    }
    OpenCsv(m_cwndFile, "cwnd.csv", "time_s,flow,cwnd_bytes");
    OpenCsv(m_ssthreshFile, "ssthresh.csv", "time_s,flow,ssthresh_bytes");
    OpenCsv(m_rttFile, "rtt.csv", "time_s,flow,rtt_ms");
    OpenCsv(m_stateFile, "cong_state.csv", "time_s,flow,old_state,new_state");
    OpenCsv(m_queueFile, "queue.csv", "time_s,queue_packets");
    OpenCsv(m_sojournFile, "queue_delay.csv", "time_s,sojourn_ms");
    OpenCsv(m_dropFile, "drops.csv", "time_s,size_bytes,cumulative_drops");
    OpenCsv(m_tputFile, "throughput.csv", "time_s,flow,goodput_mbps");
}

void
BaselineTracer::OpenCsv(std::ofstream& f, const std::string& name, const std::string& header)
{
    const std::string path = m_cfg.outDir + "/" + name;
    f.open(path, std::ios::out | std::ios::trunc);
    NS_ABORT_MSG_UNLESS(f.is_open(), "Cannot open output file " << path);
    f << std::fixed << std::setprecision(6);
    f << header << "\n";
}

void
BaselineTracer::Install()
{
    // Queue traces can be connected right now (the queue disc object already exists).
    Ptr<QueueDisc> q = m_topo.bottleneckQueue;
    q->TraceConnectWithoutContext("PacketsInQueue",
                                  MakeCallback(&BaselineTracer::OnQueuePackets, this));
    q->TraceConnectWithoutContext("SojournTime",
                                  MakeCallback(&BaselineTracer::OnQueueSojourn, this));
    q->TraceConnectWithoutContext("Drop", MakeCallback(&BaselineTracer::OnQueueDrop, this));

    // TCP sockets do not exist until the application starts, so connect shortly afterwards.
    for (uint32_t i = 0; i < m_cfg.nFlows; ++i)
    {
        Simulator::Schedule(Seconds(m_traffic.startTimes[i] + 1e-4),
                            &BaselineTracer::ConnectSenderTraces,
                            this,
                            i);
    }

    // Periodic goodput sampling.
    Simulator::Schedule(Seconds(m_cfg.throughputInterval), &BaselineTracer::SampleThroughput, this);
}

void
BaselineTracer::ConnectSenderTraces(uint32_t flow)
{
    // Each sender node has exactly one TCP socket -> SocketList/0.
    const std::string base = "/NodeList/" + std::to_string(m_topo.senders.Get(flow)->GetId()) +
                             "/$ns3::TcpL4Protocol/SocketList/0/";

    // LookupMatches() resolves OBJECT paths (not trace-source names), so check the socket itself.
    NS_ABORT_MSG_IF(Config::LookupMatches(base.substr(0, base.size() - 1)).GetN() == 0,
                    "TCP socket not found at " << base << " (trace connection failed)");

    Config::Connect(base + "CongestionWindow", MakeCallback(&BaselineTracer::OnCwnd, this));
    Config::Connect(base + "SlowStartThreshold", MakeCallback(&BaselineTracer::OnSsthresh, this));
    Config::Connect(base + "RTT", MakeCallback(&BaselineTracer::OnRtt, this));
    Config::Connect(base + "CongState", MakeCallback(&BaselineTracer::OnCongState, this));
}

uint32_t
BaselineTracer::FlowFromContext(const std::string& context) const
{
    const std::string key = "/NodeList/";
    const size_t p = context.find(key);
    NS_ABORT_MSG_IF(p == std::string::npos, "Unexpected trace context: " << context);
    const size_t s = p + key.size();
    const size_t e = context.find('/', s);
    const uint32_t nodeId = std::stoul(context.substr(s, e - s));
    auto it = m_nodeToFlow.find(nodeId);
    NS_ABORT_MSG_IF(it == m_nodeToFlow.end(), "Trace from non-sender node " << nodeId);
    return it->second;
}

void
BaselineTracer::OnCwnd(std::string context, uint32_t, uint32_t newV)
{
    m_cwndFile << Simulator::Now().GetSeconds() << "," << FlowFromContext(context) << "," << newV
               << "\n";
}

void
BaselineTracer::OnSsthresh(std::string context, uint32_t, uint32_t newV)
{
    m_ssthreshFile << Simulator::Now().GetSeconds() << "," << FlowFromContext(context) << ","
                   << newV << "\n";
}

void
BaselineTracer::OnRtt(std::string context, Time, Time newV)
{
    m_rttFile << Simulator::Now().GetSeconds() << "," << FlowFromContext(context) << ","
              << newV.GetSeconds() * 1000.0 << "\n";
}

void
BaselineTracer::OnCongState(std::string context,
                            TcpSocketState::TcpCongState_t oldV,
                            TcpSocketState::TcpCongState_t newV)
{
    m_stateFile << Simulator::Now().GetSeconds() << "," << FlowFromContext(context) << ","
                << TcpSocketState::TcpCongStateName[oldV] << ","
                << TcpSocketState::TcpCongStateName[newV] << "\n";
}

void
BaselineTracer::OnQueuePackets(uint32_t, uint32_t newV)
{
    m_queueFile << Simulator::Now().GetSeconds() << "," << newV << "\n";
}

void
BaselineTracer::OnQueueSojourn(Time sojourn)
{
    m_sojournFile << Simulator::Now().GetSeconds() << "," << sojourn.GetSeconds() * 1000.0 << "\n";
}

void
BaselineTracer::OnQueueDrop(Ptr<const QueueDiscItem> item)
{
    ++m_dropCount;
    m_dropFile << Simulator::Now().GetSeconds() << "," << item->GetSize() << "," << m_dropCount
               << "\n";
}

void
BaselineTracer::SampleThroughput()
{
    for (uint32_t i = 0; i < m_cfg.nFlows; ++i)
    {
        Ptr<PacketSink> sink = DynamicCast<PacketSink>(m_traffic.sinkApps.Get(i));
        const uint64_t rx = sink->GetTotalRx();
        const uint64_t delta = rx - m_lastRxBytes[i];
        m_lastRxBytes[i] = rx;
        const double mbps = (delta * 8.0) / m_cfg.throughputInterval / 1e6;
        m_tputFile << Simulator::Now().GetSeconds() << "," << i << "," << mbps << "\n";
    }
    if (Simulator::Now().GetSeconds() + m_cfg.throughputInterval <= m_cfg.simTime + 1e-9)
    {
        Simulator::Schedule(Seconds(m_cfg.throughputInterval),
                            &BaselineTracer::SampleThroughput,
                            this);
    }
}

void
BaselineTracer::Finalize()
{
    const QueueDisc::Stats& st = m_topo.bottleneckQueue->GetStats();
    const double dropPct = st.nTotalReceivedPackets > 0
                               ? 100.0 * st.nTotalDroppedPackets / st.nTotalReceivedPackets
                               : 0.0;

    std::ofstream s(m_cfg.outDir + "/summary.csv", std::ios::out | std::ios::trunc);
    NS_ABORT_MSG_UNLESS(s.is_open(), "Cannot open summary.csv");
    s << std::fixed << std::setprecision(6);
    s << "key,value\n";

    // parameters (so every results folder documents how it was produced)
    s << "param.simTime," << m_cfg.simTime << "\n";
    s << "param.seed," << m_cfg.seed << "\n";
    s << "param.run," << m_cfg.run << "\n";
    s << "param.bottleneckBw," << m_cfg.bottleneckBw << "\n";
    s << "param.bottleneckDelay," << m_cfg.bottleneckDelay << "\n";
    s << "param.accessBw," << m_cfg.accessBw << "\n";
    s << "param.accessDelay," << m_cfg.accessDelay << "\n";
    s << "param.queuePackets," << m_cfg.queuePackets << "\n";
    s << "param.nFlows," << m_cfg.nFlows << "\n";
    s << "param.tcpVariant," << m_cfg.tcpVariant << "\n";
    s << "param.appRate," << m_cfg.appRate << "\n";
    s << "param.segmentSize," << m_cfg.segmentSize << "\n";
    s << "param.throughputInterval," << m_cfg.throughputInterval << "\n";

    // bottleneck queue (data direction) statistics
    s << "bottleneck.received_packets," << st.nTotalReceivedPackets << "\n";
    s << "bottleneck.sent_packets," << st.nTotalSentPackets << "\n";
    s << "bottleneck.dropped_packets," << st.nTotalDroppedPackets << "\n";
    s << "bottleneck.drop_rate_percent," << dropPct << "\n";
    s << "trace.drop_events_logged," << m_dropCount << "\n";

    // per-flow results
    for (uint32_t i = 0; i < m_cfg.nFlows; ++i)
    {
        Ptr<PacketSink> sink = DynamicCast<PacketSink>(m_traffic.sinkApps.Get(i));
        const uint64_t bytes = sink->GetTotalRx();
        const double active = m_cfg.simTime - m_traffic.startTimes[i];
        s << "flow" << i << ".start_time_s," << m_traffic.startTimes[i] << "\n";
        s << "flow" << i << ".bytes_received," << bytes << "\n";
        s << "flow" << i << ".avg_goodput_mbps," << (bytes * 8.0) / active / 1e6 << "\n";
    }

    m_cwndFile.close();
    m_ssthreshFile.close();
    m_rttFile.close();
    m_stateFile.close();
    m_queueFile.close();
    m_sojournFile.close();
    m_dropFile.close();
    m_tputFile.close();
}
