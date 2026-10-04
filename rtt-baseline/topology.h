/*
 * topology.h
 * Builds the dumbbell network. Knows NOTHING about TCP variants, applications or tracing.
 *
 *   S0 --\                                      /-- R0
 *   S1 ---+-- routerLeft ==bottleneck== routerRight --+-- R1
 *   Sn --/        (FIFO queue here)                    \-- Rn
 */
#ifndef TOPOLOGY_H
#define TOPOLOGY_H

#include "sim-config.h"

#include "ns3/core-module.h"
#include "ns3/internet-module.h"
#include "ns3/network-module.h"
#include "ns3/traffic-control-module.h"

#include <vector>

struct DumbbellTopology
{
    ns3::NodeContainer senders;                     // S0..S(n-1)
    ns3::NodeContainer receivers;                   // R0..R(n-1)
    ns3::NodeContainer routers;                     // Get(0)=routerLeft, Get(1)=routerRight
    std::vector<ns3::Ipv4Address> receiverAddresses; // IPv4 address of each receiver
    ns3::Ptr<ns3::QueueDisc> bottleneckQueue;       // forward-direction queue (routerLeft -> routerRight)
};

DumbbellTopology BuildDumbbellTopology(const SimConfig& cfg);

#endif // TOPOLOGY_H
