#include "timing.hpp"
#include <fcntl.h>
#include <unistd.h>
#include <numeric>
#include <cmath>
#include <algorithm>
#include <stdexcept>
#include <pthread.h>
#include <cstdlib>

namespace zerotrace {
namespace timing {

TelemetryEngine::TelemetryEngine(const std::string& device_path) : path(device_path) {
    // O_DIRECT is strictly required for accurate storage controller latency profiling
    fd = open(device_path.c_str(), O_RDONLY | O_DIRECT | O_SYNC);
    if (fd < 0) throw std::runtime_error("Failed to open device with O_DIRECT for telemetry");
    
    // Attempt to isolate thread to core 0 to reduce context switching variance
    pin_thread_to_core(0);
}

TelemetryEngine::~TelemetryEngine() {
    if (fd >= 0) close(fd);
}

void TelemetryEngine::profile_entropy_high_state() {
    // Placeholder for setting high entropy baseline
    baseline_high_cycles = 0.0; 
}

void TelemetryEngine::profile_entropy_low_state() {
    // Placeholder for setting low entropy baseline
    baseline_low_cycles = 0.0;
}

void TelemetryEngine::pin_thread_to_core(int core_id) {
    cpu_set_t cpuset;
    CPU_ZERO(&cpuset);
    CPU_SET(core_id, &cpuset);
    pthread_setaffinity_np(pthread_self(), sizeof(cpu_set_t), &cpuset);
}

TelemetryProfile TelemetryEngine::execute_telemetry_scan(uint64_t start_lba, size_t sample_count) {
    const size_t BLOCK_SIZE = 4096; // 4KB read
    uint8_t* buffer = (uint8_t*)aligned_alloc(512, BLOCK_SIZE);
    if (!buffer) throw std::bad_alloc();
    
    std::vector<uint64_t> latencies;
    latencies.reserve(sample_count);

    // Warm-up phase to transition NVMe from APST (Autonomous Power State Transition)
    for (int i = 0; i < 50; i++) {
        read(fd, buffer, BLOCK_SIZE);
    }

    for (size_t i = 0; i < sample_count; i++) {
        lseek64(fd, (start_lba + i) * 512, SEEK_SET);
        
        uint64_t start_cycles = rdtsc();
        ssize_t bytes = read(fd, buffer, BLOCK_SIZE);
        uint64_t end_cycles = rdtsc();

        if (bytes > 0) {
            latencies.push_back(end_cycles - start_cycles);
        }
    }
    
    free(buffer);

    // --- Statistical Aggregation ---
    TelemetryProfile profile;
    profile.raw_latencies = latencies;

    if (!latencies.empty()) {
        double sum = std::accumulate(latencies.begin(), latencies.end(), 0.0);
        profile.mean_latency_cycles = sum / latencies.size();

        std::sort(latencies.begin(), latencies.end());
        profile.median_latency_cycles = latencies[latencies.size() / 2];

        double sq_sum = std::inner_product(latencies.begin(), latencies.end(), latencies.begin(), 0.0);
        profile.std_deviation = std::sqrt(sq_sum / latencies.size() - profile.mean_latency_cycles * profile.mean_latency_cycles);
    } else {
        profile.mean_latency_cycles = 0;
        profile.median_latency_cycles = 0;
        profile.std_deviation = 0;
    }

    // Statistical anomalies are calculated in Python SciPy layer
    profile.statistically_anomalous = false; 
    profile.anomaly_p_value = 1.0;

    return profile;
}

} // namespace timing
} // namespace zerotrace
