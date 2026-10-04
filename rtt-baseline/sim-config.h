/*
 * sim-config.h
 * Single place that holds EVERY tunable simulation parameter.
 * Defaults are chosen so that one NewReno flow visibly fills the bottleneck
 * queue and then overflows it (see README / handoff for the derivation).
 * No ns-3 types here on purpose: this struct is plain C++ and easy to explain.
 */
#ifndef SIM_CONFIG_H
#define SIM_CONFIG_H

#include <cstdint>
#include <string>

struct SimConfig
{
    // ---- simulation control ----
    double simTime = 60.0;  // total simulated time [s]
    uint32_t seed = 1;      // RngSeedManager::SetSeed
    uint32_t run = 1;       // RngSeedManager::SetRun (independent replications)

    // ---- topology (dumbbell) ----
    std::string bottleneckBw = "10Mbps";   // router-to-router link rate
    std::string bottleneckDelay = "20ms";  // router-to-router one-way propagation delay
    std::string accessBw = "100Mbps";      // sender->router and router->receiver rate
    std::string accessDelay = "2ms";       // one-way propagation delay of EACH access link
    uint32_t queuePackets = 100;           // bottleneck FIFO queue capacity [packets]
    uint32_t nFlows = 1;                   // number of sender/receiver pairs

    // ---- TCP / application ----
    std::string tcpVariant = "TcpNewReno"; // any ns-3 TypeId name, e.g. TcpCubic, TcpVegas
    std::string appRate = "20Mbps";        // offered load per flow (> bottleneck => saturating)
    uint32_t segmentSize = 1448;           // TCP MSS [bytes]; also the app packet size
    double appStart = 1.0;                 // first flow start time [s]
    double flowStagger = 1.0;              // extra start delay per additional flow [s]
    double startJitter = 0.2;              // random start jitter U(0, startJitter) [s] (uses seed/run)

    // ---- output ----
    std::string outDir = "results/baseline"; // relative to the directory you launch ./ns3 from
    double throughputInterval = 0.1;         // goodput sampling period [s]
};

#endif // SIM_CONFIG_H
