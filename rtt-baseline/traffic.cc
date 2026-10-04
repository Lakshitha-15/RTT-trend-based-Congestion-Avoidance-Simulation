#include "traffic.h"

#include "ns3/internet-module.h"
#include "ns3/network-module.h"

using namespace ns3;

void
ConfigureTcpDefaults(const SimConfig& cfg)
{
    const std::string typeName = "ns3::" + cfg.tcpVariant;
    TypeId tid;
    NS_ABORT_MSG_UNLESS(TypeId::LookupByNameFailSafe(typeName, &tid),
                        "Unknown TCP variant '" << typeName
                                                << "'. Try TcpNewReno, TcpLinuxReno, TcpCubic, TcpVegas, TcpBbr...");

    // Congestion-control algorithm used by every TCP socket created afterwards.
    Config::SetDefault("ns3::TcpL4Protocol::SocketType", StringValue(typeName));

    // Maximum segment size (payload bytes per TCP segment).
    Config::SetDefault("ns3::TcpSocket::SegmentSize", UintegerValue(cfg.segmentSize));

    // Initial congestion window = 10 segments (RFC 6928); stated explicitly for clarity.
    Config::SetDefault("ns3::TcpSocket::InitialCwnd", UintegerValue(10));

    // Large socket buffers (4 MiB). The ns-3 default receive buffer (128 KiB) would cap the
    // advertised window at ~90 segments, which is LESS than BDP + queue (~140 segments in the
    // default scenario). The flow would then be limited by the receiver window, never by the
    // network, and no congestion loss would ever occur.
    Config::SetDefault("ns3::TcpSocket::SndBufSize", UintegerValue(4 * 1024 * 1024));
    Config::SetDefault("ns3::TcpSocket::RcvBufSize", UintegerValue(4 * 1024 * 1024));
}

TrafficSetup
InstallTraffic(const SimConfig& cfg, const DumbbellTopology& topo)
{
    TrafficSetup setup;
    const uint16_t port = 5000;

    Ptr<UniformRandomVariable> jitter = CreateObject<UniformRandomVariable>();
    jitter->SetAttribute("Min", DoubleValue(0.0));
    jitter->SetAttribute("Max", DoubleValue(cfg.startJitter));

    for (uint32_t i = 0; i < cfg.nFlows; ++i)
    {
        // Receiver side: PacketSink listens on TCP 'port' and counts received bytes.
        PacketSinkHelper sinkHelper("ns3::TcpSocketFactory",
                                    InetSocketAddress(Ipv4Address::GetAny(), port));
        ApplicationContainer sink = sinkHelper.Install(topo.receivers.Get(i));
        sink.Start(Seconds(0.0));
        sink.Stop(Seconds(cfg.simTime));
        setup.sinkApps.Add(sink);

        // Sender side: OnOffApplication in "always on" mode = constant bit-rate source over TCP.
        OnOffHelper onoff("ns3::TcpSocketFactory",
                          InetSocketAddress(topo.receiverAddresses[i], port));
        onoff.SetConstantRate(DataRate(cfg.appRate), cfg.segmentSize);
        ApplicationContainer app = onoff.Install(topo.senders.Get(i));

        const double start = cfg.appStart + i * cfg.flowStagger + jitter->GetValue();
        NS_ABORT_MSG_IF(start >= cfg.simTime, "Flow " << i << " would start after simTime");
        app.Start(Seconds(start));
        app.Stop(Seconds(cfg.simTime));
        setup.senderApps.Add(app);
        setup.startTimes.push_back(start);
    }
    return setup;
}
