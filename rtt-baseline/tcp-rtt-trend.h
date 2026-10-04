/*
 * tcp-rtt-trend.h
 * PART 2: the proposed congestion-control algorithm "TcpRttTrend".
 *
 * TcpRttTrend IS-A TcpNewReno. It reuses ALL of NewReno's loss handling
 * (fast retransmit, fast recovery, ssthresh = flight/2 on loss, RTO) unchanged and only
 * changes how the window GROWS (and, in one rare case, shrinks) while no loss is happening.
 *
 * Pipeline:
 *   per ACK : collect the RTT value ns-3 provides (RFC 6298 SRTT)
 *   per RTT : mean of the values collected in one round trip = ONE RTT sample
 *             -> EWMA smoothing -> sliding window of W samples -> linear-regression slope
 *             -> state machine (NORMAL / EARLY_CONGESTION / CONGESTED) -> cwnd response
 */
#ifndef TCP_RTT_TREND_H
#define TCP_RTT_TREND_H

#include "ns3/core-module.h"
#include "ns3/internet-module.h"

#include <deque>
#include <functional>
#include <string>
#include <utility>

namespace ns3
{

class TcpRttTrend : public TcpNewReno
{
  public:
    enum State
    {
        NORMAL = 0,
        EARLY_CONGESTION = 1,
        CONGESTED = 2
    };

    // One row per RTT epoch (written to rtt_trend.csv by the tracer).
    struct Record
    {
        double timeS;
        uint32_t nodeId;
        double rttInMs;       // mean of the ns-3 RTT values received in this epoch (the RTT sample)
        double smoothedMs;    // EWMA of the epoch samples
        double baseRttMs;     // minimum smoothed RTT seen so far
        double queueDelayMs;  // smoothedMs - baseRttMs (estimate of queueing delay)
        double slopeMsPerS;   // regression slope over the window (NaN until window is full)
        int state;
        uint32_t cwndBytes;
        uint32_t ssthreshBytes;
    };

    // One row per state change (written to rtt_trend_events.csv).
    struct Transition
    {
        double timeS;
        uint32_t nodeId;
        int oldState;
        int newState;
        const char* reason;
        double slopeMsPerS;
        double queueDelayMs;
    };

    static TypeId GetTypeId();
    TcpRttTrend();
    TcpRttTrend(const TcpRttTrend& other);
    ~TcpRttTrend() override;

    std::string GetName() const override;
    Ptr<TcpCongestionOps> Fork() override;

    void PktsAcked(Ptr<TcpSocketState> tcb, uint32_t segmentsAcked, const Time& rtt) override;
    void IncreaseWindow(Ptr<TcpSocketState> tcb, uint32_t segmentsAcked) override;
    void CongestionStateSet(Ptr<TcpSocketState> tcb,
                            const TcpSocketState::TcpCongState_t newState) override;

    // Logging hooks (set by BaselineTracer). Plain std::function: simple and explainable.
    static void SetRecordSink(std::function<void(const Record&)> sink);
    static void SetTransitionSink(std::function<void(const Transition&)> sink);
    static const char* StateName(int state);

  protected:
    uint32_t SlowStart(Ptr<TcpSocketState> tcb, uint32_t segmentsAcked) override;
    void CongestionAvoidance(Ptr<TcpSocketState> tcb, uint32_t segmentsAcked) override;

  private:
    void EndEpoch(Ptr<TcpSocketState> tcb, double now);
    double ComputeSlope(bool& valid) const;
    void UpdateState(double now, double slope, bool valid, double queueDelayMs);
    void SetState(State s, const char* reason, double now);
    void MaybeDecrease(Ptr<TcpSocketState> tcb, double now);
    double GrowthFactor() const;

    // ---- configurable parameters (ns-3 attributes) ----
    uint32_t m_windowSize;         // W: per-RTT samples in the regression window
    double m_alpha;                // EWMA gain
    double m_slopeEnter;           // ms/s: slope needed to ENTER early congestion
    double m_slopeExit;            // ms/s: slope below which early congestion may END
    Time m_persist;                // how long a condition must hold ("persistent")
    double m_minQueueDelayMs;      // ignore trends while estimated queueing delay is below this
    double m_congDelayMs;          // queueing delay at which state becomes CONGESTED
    double m_exitFraction;         // hysteresis: exit thresholds = fraction * entry thresholds
    double m_growthReduction;      // beta: fraction of additive increase removed in EARLY state
    double m_congestedDecrease;    // gamma: multiplicative decrease (delay-triggered CONGESTED only)
    double m_decreaseIntervalRtts; // minimum spacing between two such decreases, in RTTs
    uint32_t m_minCwndSegs;        // floor for cwnd reductions
    uint32_t m_maxCwndSegs;        // cap for cwnd (0 = no cap)

    // ---- internal state ----
    State m_state;
    bool m_haveEwma;
    double m_ewma;
    double m_baseRtt;
    Time m_lastInput;
    double m_epochStart;   // start time of the current RTT epoch (-1 = none)
    double m_epochSum;     // sum of RTT values [ms] collected in the epoch
    uint32_t m_epochCount; // number of values collected in the epoch
    std::deque<std::pair<double, double>> m_window; // (time [s], smoothed RTT [ms])
    double m_riseStart;
    double m_fallStart;
    bool m_lossActive;
    double m_lastDecrease;
    double m_growthResidual;
    double m_lastSlope;
    double m_lastQd;

    static std::function<void(const Record&)> s_recordSink;
    static std::function<void(const Transition&)> s_transitionSink;
};

} // namespace ns3

#endif // TCP_RTT_TREND_H
