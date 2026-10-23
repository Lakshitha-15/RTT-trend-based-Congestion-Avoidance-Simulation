#include "topology.h"

#include "ns3/point-to-point-module.h"

#include <string>
#include <vector>

using namespace ns3;

DumbbellTopology
BuildDumbbellTopology(const SimConfig& cfg)
{
    NS_ABORT_MSG_IF(cfg.nFlows < 1 || cfg.nFlows > 250, "nFlows must be in [1, 250]");

    DumbbellTopology topo;

    // 1) Nodes
    topo.senders.Create(cfg.nFlows);
    topo.receivers.Create(cfg.nFlows);
    topo.routers.Create(2);
    Ptr<Node> routerLeft = topo.routers.Get(0);
    Ptr<Node> routerRight = topo.routers.Get(1);

    // 2) Link models (PointToPointHelper = full-duplex point-to-point channel + 2 devices)
    PointToPointHelper accessLink;
    accessLink.SetDeviceAttribute("DataRate", StringValue(cfg.accessBw));
    accessLink.SetChannelAttribute("Delay", StringValue(cfg.accessDelay));

    PointToPointHelper bottleneckLink;
    bottleneckLink.SetDeviceAttribute("DataRate", StringValue(cfg.bottleneckBw));
    bottleneckLink.SetChannelAttribute("Delay", StringValue(cfg.bottleneckDelay));
    // The NetDevice's own transmit queue is made tiny (1 packet) so that the
    // "real" buffering happens in the traffic-control queue disc installed below.
    // That queue disc is the one we configure (size) and trace (occupancy, drops, delay).
    bottleneckLink.SetQueue("ns3::DropTailQueue<Packet>", "MaxSize", StringValue("1p"));

    // 3) Create the links
    NetDeviceContainer bottleneckDevices = bottleneckLink.Install(routerLeft, routerRight);
    std::vector<NetDeviceContainer> senderLinks;
    std::vector<NetDeviceContainer> receiverLinks;
    NetDeviceContainer allAccessDevices;
    for (uint32_t i = 0; i < cfg.nFlows; ++i)
    {
        NetDeviceContainer s = accessLink.Install(topo.senders.Get(i), routerLeft);
        NetDeviceContainer r = accessLink.Install(routerRight, topo.receivers.Get(i));
        senderLinks.push_back(s);
        receiverLinks.push_back(r);
        allAccessDevices.Add(s);
        allAccessDevices.Add(r);
    }

    // 4) Protocol stack (IPv4 + TCP + UDP + traffic-control layer) on every node.
    //    NOTE: TCP defaults (SocketType, buffers...) must already be set before this call.
    InternetStackHelper stack;
    stack.Install(topo.senders);
    stack.Install(topo.receivers);
    stack.Install(topo.routers);

    // 5) Queue discs. Must be installed AFTER the stack but BEFORE IP addresses are
    //    assigned (otherwise ns-3 installs its default FqCoDel queue disc automatically).
    TrafficControlHelper tchBottleneck;
    tchBottleneck.SetRootQueueDisc("ns3::FifoQueueDisc",
                                   "MaxSize",
                                   StringValue(std::to_string(cfg.queuePackets) + "p"));
    QueueDiscContainer bottleneckQdiscs = tchBottleneck.Install(bottleneckDevices);
    // Install() returns one queue disc per device, in device order:
    // Get(0) is on routerLeft (data direction), Get(1) is on routerRight (ACK direction).
    topo.bottleneckQueue = bottleneckQdiscs.Get(0);

    // Access links: large FIFO so they never drop; the bottleneck is the only loss point.
    TrafficControlHelper tchAccess;
    tchAccess.SetRootQueueDisc("ns3::FifoQueueDisc", "MaxSize", StringValue("1000p"));
    tchAccess.Install(allAccessDevices);

    // 6) IPv4 addressing: one /24 subnet per link.
    Ipv4AddressHelper address;
    address.SetBase("10.0.0.0", "255.255.255.0");
    address.Assign(bottleneckDevices);
    for (uint32_t i = 0; i < cfg.nFlows; ++i)
    {
        const std::string sNet = "10.1." + std::to_string(i + 1) + ".0";
        const std::string rNet = "10.2." + std::to_string(i + 1) + ".0";
        address.SetBase(sNet.c_str(), "255.255.255.0");
        address.Assign(senderLinks[i]);
        address.SetBase(rNet.c_str(), "255.255.255.0");
        Ipv4InterfaceContainer rIf = address.Assign(receiverLinks[i]);
        // receiverLinks[i] = {routerRight device, receiver device} -> receiver is index 1
        topo.receiverAddresses.push_back(rIf.GetAddress(1));
    }

    // 7) Static routes computed from the topology graph.
    Ipv4GlobalRoutingHelper::PopulateRoutingTables();

    return topo;
}
