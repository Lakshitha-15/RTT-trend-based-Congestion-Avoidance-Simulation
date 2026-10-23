/*
 * traffic.h
 * TCP configuration + application layer. Knows nothing about tracing.
 */
#ifndef TRAFFIC_H
#define TRAFFIC_H

#include "sim-config.h"
#include "topology.h"

#include "ns3/applications-module.h"
#include "ns3/core-module.h"

#include <vector>

struct TrafficSetup
{
    ns3::ApplicationContainer senderApps;  // OnOffApplication on each sender
    ns3::ApplicationContainer sinkApps;    // PacketSink on each receiver
    std::vector<double> startTimes;        // actual start time of each flow [s]
};

// Must be called BEFORE BuildDumbbellTopology() (it sets global attribute defaults).
void ConfigureTcpDefaults(const SimConfig& cfg);

TrafficSetup InstallTraffic(const SimConfig& cfg, const DumbbellTopology& topo);

#endif // TRAFFIC_H
