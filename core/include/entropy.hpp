#pragma once
#include "device.hpp"
#include <vector>
#include <cstdint>

namespace zerotrace {

// ─────────────────────────────────────────────
// Entropy Analysis
// ─────────────────────────────────────────────

// Main entry point.
// Samples ~10% of the device:
//   - First 1% of blocks
//   - Last 1% of blocks
//   - Random 8% scattered across the device
// Computes Shannon entropy on combined sample.
// Interprets result based on which WipeMode was used.
//
// IMPORTANT: Call this AFTER the wipe completes, passing the same
// WipeMode that was used. The interpretation of entropy differs:
//   - After CLEAR:            expect H < 0.1 bits/byte (near-zero entropy)
//   - After PURGE:            expect H > 7.5 bits/byte (near-maximum entropy)
//   - After FIRMWARE_DELETION: accept H < 0.5 OR H > 7.5 (vendor-specific result)
EntropyResult analyze_entropy(
    const std::string& device_path,
    WipeMode           mode_used
);

// Lower-level: compute Shannon entropy on a byte buffer
// Returns value between 0.0 (all same byte) and 8.0 (perfect random)
double compute_shannon_entropy(const uint8_t* data, size_t length);

// Generate sampling offsets for a device of given size
// Returns vector of byte offsets to sample from
std::vector<uint64_t> generate_sample_offsets(
    uint64_t device_size_bytes,
    size_t   sample_block_size = 4096
);

} // namespace zerotrace
