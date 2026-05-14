#pragma once

#include <vector>
#include <string>
#include <cstdint>
#include <sched.h>

namespace zerotrace {
namespace timing {

struct TelemetryProfile {
    double mean_latency_cycles;
    double median_latency_cycles;
    double std_deviation;
    std::vector<uint64_t> raw_latencies;
    bool statistically_anomalous;
    double anomaly_p_value;
};

class TelemetryEngine {
public:
    TelemetryEngine(const std::string& device_path);
    ~TelemetryEngine();

    // Baseline profiling on known physical states
    void profile_entropy_high_state();
    void profile_entropy_low_state();

    // The core benchmarking function
    TelemetryProfile execute_telemetry_scan(uint64_t start_lba, size_t sample_count);

private:
    int fd;
    std::string path;
    double baseline_high_cycles;
    double baseline_low_cycles;

    // Pin thread to isolate from OS scheduler jitter
    void pin_thread_to_core(int core_id);

    // X86/X64 exact CPU cycle counter
    inline uint64_t rdtsc() {
        unsigned int lo, hi;
        // CPUID serializes execution to prevent out-of-order execution skew
        __asm__ __volatile__ (
            "cpuid \n"
            "rdtsc \n"
            : "=a" (lo), "=d" (hi)
            :: "%rbx", "%rcx"
        );
        return ((uint64_t)hi << 32) | lo;
    }
};

} // namespace timing
} // namespace zerotrace
