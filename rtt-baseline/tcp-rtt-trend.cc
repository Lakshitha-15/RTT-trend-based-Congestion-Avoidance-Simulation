#include "tcp-rtt-trend.h"

#include <algorithm>
#include <cmath>
#include <limits>

namespace ns3
{

NS_LOG_COMPONENT_DEFINE("TcpRttTrend");
NS_OBJECT_ENSURE_REGISTERED(TcpRttTrend);

std::function<void(const TcpRttTrend::Record&)> TcpRttTrend::s_recordSink;
std::function<void(const TcpRttTrend::Transition&)> TcpRttTrend::s_transitionSink;

TypeId
TcpRttTrend::GetTypeId()
{
    static TypeId tid =
        TypeId("ns3::TcpRttTrend")
            .SetParent<TcpNewReno>()
            .SetGroupName("Internet")
            .AddConstructor<TcpRttTrend>()
            .AddAttribute("WindowSize",
                          "Number of per-RTT samples in the regression window",
                          UintegerValue(15),
                          MakeUintegerAccessor(&TcpRttTrend::m_windowSize),
                          MakeUintegerChecker<uint32_t>(3))
            .AddAttribute("EwmaAlpha",
                          "EWMA gain over per-RTT samples: s = alpha*x + (1-alpha)*s. 1.0 = no smoothing",
                          DoubleValue(0.5),
                          MakeDoubleAccessor(&TcpRttTrend::m_alpha),
                          MakeDoubleChecker<double>(0.001, 1.0))
            .AddAttribute("SlopeEnter",
                          "RTT slope [ms/s] needed to enter EARLY_CONGESTION",
                          DoubleValue(3.0),
                          MakeDoubleAccessor(&TcpRttTrend::m_slopeEnter),
                          MakeDoubleChecker<double>())
            .AddAttribute("SlopeExit",
                          "RTT slope [ms/s] at or below which EARLY_CONGESTION may end",
                          DoubleValue(1.0),
                          MakeDoubleAccessor(&TcpRttTrend::m_slopeExit),
                          MakeDoubleChecker<double>())
            .AddAttribute("PersistTime",
                          "How long the entry/exit slope condition must hold continuously",
                          TimeValue(Seconds(0.3)),
                          MakeTimeAccessor(&TcpRttTrend::m_persist),
                          MakeTimeChecker())
            .AddAttribute("MinQueueDelayMs",
                          "Estimated queueing delay [ms] below which RTT trends are ignored",
                          DoubleValue(10.0),
                          MakeDoubleAccessor(&TcpRttTrend::m_minQueueDelayMs),
                          MakeDoubleChecker<double>(0.0))
            .AddAttribute("CongDelayMs",
                          "Estimated queueing delay [ms] at which the state becomes CONGESTED",
                          DoubleValue(40.0),
                          MakeDoubleAccessor(&TcpRttTrend::m_congDelayMs),
                          MakeDoubleChecker<double>(0.0))
            .AddAttribute("ExitFraction",
                          "Hysteresis: delay exit thresholds = ExitFraction * entry thresholds",
                          DoubleValue(0.5),
                          MakeDoubleAccessor(&TcpRttTrend::m_exitFraction),
                          MakeDoubleChecker<double>(0.0, 1.0))
            .AddAttribute("GrowthReduction",
                          "Response strength beta: fraction of the additive increase removed while the "
                          "state is not NORMAL (0 = no response / monitor-only, 1 = freeze cwnd)",
                          DoubleValue(1.0),
                          MakeDoubleAccessor(&TcpRttTrend::m_growthReduction),
                          MakeDoubleChecker<double>(0.0, 1.0))
            .AddAttribute("CongestedDecrease",
                          "Multiplicative cwnd decrease applied (rate limited) when CONGESTED is "
                          "reached by queueing delay before any loss (0 = disabled)",
                          DoubleValue(0.1),
                          MakeDoubleAccessor(&TcpRttTrend::m_congestedDecrease),
                          MakeDoubleChecker<double>(0.0, 0.9))
            .AddAttribute("DecreaseIntervalRtts",
                          "Minimum time between two delay-triggered decreases, in smoothed RTTs",
                          DoubleValue(4.0),
                          MakeDoubleAccessor(&TcpRttTrend::m_decreaseIntervalRtts),
                          MakeDoubleChecker<double>(0.0))
            .AddAttribute("MinCwndSegments",
                          "Lower bound for cwnd reductions made by this algorithm [segments]",
                          UintegerValue(4),
                          MakeUintegerAccessor(&TcpRttTrend::m_minCwndSegs),
                          MakeUintegerChecker<uint32_t>(1))
            .AddAttribute("MaxCwndSegments",
                          "Upper bound for cwnd [segments]; 0 = no bound",
                          UintegerValue(0),
                          MakeUintegerAccessor(&TcpRttTrend::m_maxCwndSegs),
                          MakeUintegerChecker<uint32_t>());
    return tid;
}

TcpRttTrend::TcpRttTrend()
    : TcpNewReno(),
      m_windowSize(15),
      m_alpha(0.5),
      m_slopeEnter(3.0),
      m_slopeExit(1.0),
      m_persist(Seconds(0.3)),
      m_minQueueDelayMs(10.0),
      m_congDelayMs(40.0),
      m_exitFraction(0.5),
      m_growthReduction(1.0),
      m_congestedDecrease(0.1),
      m_decreaseIntervalRtts(4.0),
      m_minCwndSegs(4),
      m_maxCwndSegs(0),
      m_state(NORMAL),
      m_haveEwma(false),
      m_ewma(0.0),
      m_baseRtt(std::numeric_limits<double>::max()),
      m_lastInput(Seconds(0)),
      m_epochStart(-1.0),
      m_epochSum(0.0),
      m_epochCount(0),
      m_riseStart(-1.0),
      m_fallStart(-1.0),
      m_lossActive(false),
      m_lastDecrease(-1e9),
      m_growthResidual(0.0),
      m_lastSlope(std::numeric_limits<double>::quiet_NaN()),
      m_lastQd(0.0)
{
}

TcpRttTrend::TcpRttTrend(const TcpRttTrend& other)
    : TcpNewReno(other),
      m_windowSize(other.m_windowSize),
      m_alpha(other.m_alpha),
      m_slopeEnter(other.m_slopeEnter),
      m_slopeExit(other.m_slopeExit),
      m_persist(other.m_persist),
      m_minQueueDelayMs(other.m_minQueueDelayMs),
      m_congDelayMs(other.m_congDelayMs),
      m_exitFraction(other.m_exitFraction),
      m_growthReduction(other.m_growthReduction),
      m_congestedDecrease(other.m_congestedDecrease),
      m_decreaseIntervalRtts(other.m_decreaseIntervalRtts),
      m_minCwndSegs(other.m_minCwndSegs),
      m_maxCwndSegs(other.m_maxCwndSegs),
      m_state(NORMAL), // a forked socket starts with a clean detector
      m_haveEwma(false),
      m_ewma(0.0),
      m_baseRtt(std::numeric_limits<double>::max()),
      m_lastInput(Seconds(0)),
      m_epochStart(-1.0),
      m_epochSum(0.0),
      m_epochCount(0),
      m_riseStart(-1.0),
      m_fallStart(-1.0),
      m_lossActive(false),
      m_lastDecrease(-1e9),
      m_growthResidual(0.0),
      m_lastSlope(std::numeric_limits<double>::quiet_NaN()),
      m_lastQd(0.0)
{
}

TcpRttTrend::~TcpRttTrend()
{
}

std::string
TcpRttTrend::GetName() const
{
    return "TcpRttTrend";
}

Ptr<TcpCongestionOps>
TcpRttTrend::Fork()
{
    return CopyObject<TcpRttTrend>(this);
}

void
TcpRttTrend::SetRecordSink(std::function<void(const Record&)> sink)
{
    s_recordSink = std::move(sink);
}

void
TcpRttTrend::SetTransitionSink(std::function<void(const Transition&)> sink)
{
    s_transitionSink = std::move(sink);
}

const char*
TcpRttTrend::StateName(int state)
{
    switch (state)
    {
    case NORMAL:
        return "NORMAL";
    case EARLY_CONGESTION:
        return "EARLY_CONGESTION";
    default:
        return "CONGESTED";
    }
}

// ---------------------------------------------------------------------------
// Detector
// ---------------------------------------------------------------------------
// Called by ns-3 for every ACK that acknowledges new data. We only COLLECT here; the actual
// processing happens once per round trip in EndEpoch().
void
TcpRttTrend::PktsAcked(Ptr<TcpSocketState> tcb, uint32_t segmentsAcked, const Time& rtt)
{
    TcpNewReno::PktsAcked(tcb, segmentsAcked, rtt);

    // 'rtt' is TcpSocketBase's m_tcb->m_lastRtt = the RFC 6298 smoothed RTT after the latest
    // measurement. It is zero before the first measurement. Duplicate ACKs re-send the SAME
    // value (no new measurement), so an unchanged value is skipped.
    if (rtt.IsZero() || rtt == m_lastInput)
    {
        return;
    }
    m_lastInput = rtt;

    const double now = Simulator::Now().GetSeconds();
    const double x = rtt.GetSeconds() * 1000.0; // ms

    if (m_epochStart < 0.0)
    {
        m_epochStart = now;
    }
    m_epochSum += x;
    ++m_epochCount;

    // An epoch lasts one (current) round-trip time.
    if (now - m_epochStart >= x / 1000.0)
    {
        EndEpoch(tcb, now);
    }
}

// One RTT sample per round trip -> smoothing -> window -> slope -> state -> response.
void
TcpRttTrend::EndEpoch(Ptr<TcpSocketState> tcb, double now)
{
    const double sample = m_epochSum / m_epochCount; // ms
    m_epochStart = -1.0;
    m_epochSum = 0.0;
    m_epochCount = 0;

    // 1) EWMA smoothing of the per-RTT samples
    m_ewma = m_haveEwma ? m_alpha * sample + (1.0 - m_alpha) * m_ewma : sample;
    m_haveEwma = true;

    // 2) base RTT and queueing-delay estimate
    m_baseRtt = std::min(m_baseRtt, m_ewma);
    const double qd = m_ewma - m_baseRtt;

    // 3) sliding window of the last W smoothed samples
    m_window.emplace_back(now, m_ewma);
    while (m_window.size() > m_windowSize)
    {
        m_window.pop_front();
    }

    // 4) regression slope [ms/s] (only once the window is full)
    bool valid = false;
    const double slope = (m_window.size() >= m_windowSize) ? ComputeSlope(valid) : 0.0;
    m_lastSlope = valid ? slope : std::numeric_limits<double>::quiet_NaN();
    m_lastQd = qd;

    // 5) state machine and 6) response
    UpdateState(now, slope, valid, qd);
    MaybeDecrease(tcb, now);

    if (s_recordSink)
    {
        Record r;
        r.timeS = now;
        r.nodeId = Simulator::GetContext();
        r.rttInMs = sample;
        r.smoothedMs = m_ewma;
        r.baseRttMs = m_baseRtt;
        r.queueDelayMs = qd;
        r.slopeMsPerS = m_lastSlope;
        r.state = m_state;
        r.cwndBytes = tcb->m_cWnd.Get();
        r.ssthreshBytes = tcb->m_ssThresh.Get();
        s_recordSink(r);
    }
}

// Ordinary least squares slope of smoothed RTT [ms] against time [s] over the window:
//   slope = sum((t_i - t_mean)(y_i - y_mean)) / sum((t_i - t_mean)^2)
double
TcpRttTrend::ComputeSlope(bool& valid) const
{
    valid = false;
    const double n = static_cast<double>(m_window.size());
    double sumT = 0.0;
    double sumY = 0.0;
    for (const auto& p : m_window)
    {
        sumT += p.first;
        sumY += p.second;
    }
    const double meanT = sumT / n;
    const double meanY = sumY / n;
    double num = 0.0;
    double den = 0.0;
    for (const auto& p : m_window)
    {
        const double dt = p.first - meanT;
        num += dt * (p.second - meanY);
        den += dt * dt;
    }
    if (den < 1e-12)
    {
        return 0.0;
    }
    valid = true;
    return num / den;
}

void
TcpRttTrend::SetState(State s, const char* reason, double now)
{
    if (s == m_state)
    {
        return;
    }
    if (s_transitionSink)
    {
        Transition t;
        t.timeS = now;
        t.nodeId = Simulator::GetContext();
        t.oldState = m_state;
        t.newState = s;
        t.reason = reason;
        t.slopeMsPerS = m_lastSlope;
        t.queueDelayMs = m_lastQd;
        s_transitionSink(t);
    }
    m_state = s;
    m_riseStart = -1.0; // restart persistence timers after every state change
    m_fallStart = -1.0;
}

void
TcpRttTrend::UpdateState(double now, double slope, bool valid, double qd)
{
    const bool delayCongested = qd >= m_congDelayMs;
    const double persist = m_persist.GetSeconds();

    switch (m_state)
    {
    case NORMAL:
        if (m_lossActive)
        {
            SetState(CONGESTED, "loss", now);
        }
        else if (delayCongested)
        {
            SetState(CONGESTED, "queue_delay", now);
        }
        else
        {
            const bool rising = valid && slope >= m_slopeEnter && qd >= m_minQueueDelayMs;
            if (rising)
            {
                if (m_riseStart < 0.0)
                {
                    m_riseStart = now;
                }
                if (now - m_riseStart >= persist)
                {
                    SetState(EARLY_CONGESTION, "rtt_trend", now);
                }
            }
            else
            {
                m_riseStart = -1.0;
            }
        }
        break;

    case EARLY_CONGESTION:
        if (m_lossActive)
        {
            SetState(CONGESTED, "loss", now);
        }
        else if (delayCongested)
        {
            SetState(CONGESTED, "queue_delay", now);
        }
        else if (qd < m_exitFraction * m_minQueueDelayMs)
        {
            SetState(NORMAL, "queue_drained", now);
        }
        else
        {
            const bool flat = valid && slope <= m_slopeExit;
            if (flat)
            {
                if (m_fallStart < 0.0)
                {
                    m_fallStart = now;
                }
                if (now - m_fallStart >= persist)
                {
                    SetState(NORMAL, "trend_flat", now);
                }
            }
            else
            {
                m_fallStart = -1.0;
            }
        }
        break;

    case CONGESTED:
        if (!m_lossActive && qd < m_exitFraction * m_congDelayMs)
        {
            SetState(EARLY_CONGESTION, "congestion_cleared", now);
        }
        break;
    }
}

// Loss notifications come from TcpSocketBase through the standard NewReno hook.
void
TcpRttTrend::CongestionStateSet(Ptr<TcpSocketState> tcb,
                                const TcpSocketState::TcpCongState_t newState)
{
    TcpNewReno::CongestionStateSet(tcb, newState);
    const double now = Simulator::Now().GetSeconds();
    if (newState == TcpSocketState::CA_RECOVERY || newState == TcpSocketState::CA_LOSS)
    {
        m_lossActive = true;
        SetState(CONGESTED, "loss", now);
    }
    else if (newState == TcpSocketState::CA_OPEN)
    {
        m_lossActive = false;
    }
}

// ---------------------------------------------------------------------------
// Response
// ---------------------------------------------------------------------------
double
TcpRttTrend::GrowthFactor() const
{
    switch (m_state)
    {
    case NORMAL:
        return 1.0;
    default: // EARLY_CONGESTION and CONGESTED: response strength beta applies in both
        return 1.0 - m_growthReduction;
    }
}

uint32_t
TcpRttTrend::SlowStart(Ptr<TcpSocketState> tcb, uint32_t segmentsAcked)
{
    if (m_state != NORMAL && m_growthReduction > 0.0)
    {
        // Early warning during slow start: stop exponential growth NOW by making
        // ssthresh = cwnd. IncreaseWindow() then continues in congestion avoidance.
        tcb->m_ssThresh = std::min(tcb->m_ssThresh.Get(), tcb->m_cWnd.Get());
        return segmentsAcked;
    }
    return TcpNewReno::SlowStart(tcb, segmentsAcked);
}

void
TcpRttTrend::CongestionAvoidance(Ptr<TcpSocketState> tcb, uint32_t segmentsAcked)
{
    const double factor = GrowthFactor();
    if (factor >= 1.0)
    {
        TcpNewReno::CongestionAvoidance(tcb, segmentsAcked); // identical to the baseline
        return;
    }
    if (segmentsAcked == 0 || factor <= 0.0)
    {
        return;
    }
    // NewReno adds seg^2/cwnd bytes per ACK (~1 segment per RTT). We add (1-beta) of that,
    // carrying the fractional bytes over in m_growthResidual.
    const double seg = static_cast<double>(tcb->m_segmentSize);
    m_growthResidual += factor * seg * seg / static_cast<double>(tcb->m_cWnd.Get());
    const uint32_t whole = static_cast<uint32_t>(m_growthResidual);
    if (whole > 0)
    {
        tcb->m_cWnd += whole;
        m_growthResidual -= whole;
    }
}

void
TcpRttTrend::IncreaseWindow(Ptr<TcpSocketState> tcb, uint32_t segmentsAcked)
{
    TcpNewReno::IncreaseWindow(tcb, segmentsAcked);
    if (m_maxCwndSegs > 0)
    {
        const uint32_t cap = m_maxCwndSegs * tcb->m_segmentSize;
        if (tcb->m_cWnd.Get() > cap)
        {
            tcb->m_cWnd = cap;
        }
    }
}

// Multiplicative decrease, used ONLY when the queueing delay alone says "CONGESTED"
// (no loss yet). After a loss NewReno has already reduced cwnd, so nothing is added.
void
TcpRttTrend::MaybeDecrease(Ptr<TcpSocketState> tcb, double now)
{
    if (m_state != CONGESTED || m_lossActive || m_congestedDecrease <= 0.0 ||
        tcb->m_congState != TcpSocketState::CA_OPEN)
    {
        return;
    }
    const double interval = m_decreaseIntervalRtts * m_ewma / 1000.0;
    if (now - m_lastDecrease < interval)
    {
        return;
    }
    const uint32_t floorBytes = m_minCwndSegs * tcb->m_segmentSize;
    const uint32_t target = std::max(
        floorBytes,
        static_cast<uint32_t>(static_cast<double>(tcb->m_cWnd.Get()) * (1.0 - m_congestedDecrease)));
    if (target < tcb->m_cWnd.Get())
    {
        tcb->m_cWnd = target;
        tcb->m_ssThresh = target; // stay in congestion avoidance
        m_lastDecrease = now;
    }
}

} // namespace ns3
