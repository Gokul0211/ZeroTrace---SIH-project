#include "entropy.hpp"
#include <fcntl.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <linux/fs.h>
#include <cmath>
#include <random>
#include <stdexcept>
#include <cstring>
#include <algorithm>

namespace zerotrace {

double compute_shannon_entropy(const uint8_t* data, size_t length) {
    if (length == 0) return 0.0;

    uint64_t freq[256] = {};
    for (size_t i = 0; i < length; i++) {
        freq[data[i]]++;
    }

    double H = 0.0;
    for (int i = 0; i < 256; i++) {
        if (freq[i] == 0) continue;
        double p = static_cast<double>(freq[i]) / static_cast<double>(length);
        H -= p * log2(p);
    }
    return H;
}

std::vector<uint64_t> generate_sample_offsets(uint64_t device_size_bytes, size_t sample_block_size) {
    std::vector<uint64_t> offsets;
    uint64_t total_blocks = device_size_bytes / sample_block_size;
    if (total_blocks == 0) return offsets;

    // First 1%
    uint64_t first_pct = std::max(static_cast<uint64_t>(1), total_blocks / 100);
    for (uint64_t i = 0; i < first_pct; i++) {
        offsets.push_back(i * sample_block_size);
    }

    // Last 1%
    uint64_t last_pct_start = total_blocks - first_pct;
    for (uint64_t i = last_pct_start; i < total_blocks; i++) {
        offsets.push_back(i * sample_block_size);
    }

    // Random 8%
    std::mt19937_64 rng(std::random_device{}());
    std::uniform_int_distribution<uint64_t> dist(0, total_blocks - 1);
    uint64_t random_count = total_blocks * 8 / 100;
    random_count = std::max(random_count, static_cast<uint64_t>(100));  // At least 100 random samples
    for (uint64_t i = 0; i < random_count; i++) {
        offsets.push_back(dist(rng) * sample_block_size);
    }

    return offsets;
}

EntropyResult analyze_entropy(const std::string& device_path, WipeMode mode_used) {
    EntropyResult result;

    int fd = open(device_path.c_str(), O_RDONLY | O_DIRECT);
    if (fd < 0) {
        result.state = "ERROR: Cannot open device for entropy analysis";
        result.wipe_verified = false;
        return result;
    }

    uint64_t device_size = 0;
    ioctl(fd, BLKGETSIZE64, &device_size);

    const size_t SAMPLE_BLOCK = 4096;
    std::vector<uint64_t> offsets = generate_sample_offsets(device_size, SAMPLE_BLOCK);

    // Collect all samples
    uint64_t global_freq[256] = {};
    uint64_t total_bytes_sampled = 0;

    uint8_t* buf = static_cast<uint8_t*>(aligned_alloc(512, SAMPLE_BLOCK));
    if (!buf) {
        close(fd);
        result.state = "ERROR: aligned_alloc failed";
        result.wipe_verified = false;
        return result;
    }

    for (uint64_t offset : offsets) {
        if (lseek64(fd, static_cast<off64_t>(offset), SEEK_SET) < 0) continue;
        ssize_t n = read(fd, buf, SAMPLE_BLOCK);
        if (n <= 0) continue;

        for (ssize_t i = 0; i < n; i++) {
            global_freq[buf[i]]++;
        }
        total_bytes_sampled += n;
    }

    free(buf);
    close(fd);

    // Compute global entropy
    double H = 0.0;
    for (int i = 0; i < 256; i++) {
        if (global_freq[i] == 0) continue;
        double p = static_cast<double>(global_freq[i]) / static_cast<double>(total_bytes_sampled);
        H -= p * log2(p);
    }

    result.entropy_bits        = H;
    result.blocks_sampled      = offsets.size();
    result.total_blocks        = device_size / SAMPLE_BLOCK;
    result.sample_coverage_pct = static_cast<double>(offsets.size()) / static_cast<double>(result.total_blocks) * 100.0;

    // Interpret based on mode
    switch (mode_used) {
        case WipeMode::CLEAR:
            result.wipe_verified = (H < 0.1);
            result.state = result.wipe_verified ? "ZERO_FILL_CONFIRMED" : "CLEAR_FAILED";
            break;

        case WipeMode::PURGE:
            result.wipe_verified = (H > 7.5);
            result.state = result.wipe_verified ? "RANDOM_FILL_CONFIRMED" : "PURGE_FAILED";
            break;

        case WipeMode::FIRMWARE_DELETION:
            // After firmware erase, drive may return zeros, vendor pattern, or random
            // Accept both near-zero and near-max entropy
            result.wipe_verified = (H < 0.5 || H > 7.5);
            if (H < 0.5)        result.state = "FIRMWARE_ERASE_CONFIRMED (zero-fill)";
            else if (H > 7.5)   result.state = "FIRMWARE_ERASE_CONFIRMED (encrypted/random)";
            else                result.state = "VERIFY_MANUALLY (vendor-specific pattern)";
            break;
    }

    return result;
}

} // namespace zerotrace
