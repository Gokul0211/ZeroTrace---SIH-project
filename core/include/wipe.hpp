#pragma once
#include "device.hpp"
#include <functional>

namespace zerotrace {

// ─────────────────────────────────────────────
// Pre-wipe preparation
// ─────────────────────────────────────────────

// Must be called before any wipe operation.
// Removes HPA and DCO if present, re-reads device size.
// Returns updated DeviceInfo with correct size.
// Throws if preparation fails critically.
DeviceInfo prepare_device_for_wipe(const DeviceInfo& info);

// Compute SHA-256 hash of first 1MB of device (for certificate)
std::string hash_first_mb(const std::string& device_path);

// ─────────────────────────────────────────────
// Clear Mode
// ─────────────────────────────────────────────

// Write zeros to every LBA of the device using O_DIRECT + O_SYNC.
// Block size: 1MB chunks. Aligned buffer.
// Calls progress_cb periodically.
// Returns WipeResult with timing and hash data.
WipeResult wipe_clear(
    const DeviceInfo& device,
    ProgressCallback  progress_cb
);

// ─────────────────────────────────────────────
// Purge Mode
// ─────────────────────────────────────────────

// For SSDs (SATA): ATA Secure Erase Enhanced
// For SSDs (NVMe): NVMe Sanitize (Crypto Erase preferred)
// For HDDs:        AES-256 encrypt entire drive, discard key, then urandom overwrite
// Calls progress_cb during overwrite phase.
WipeResult wipe_purge(
    const DeviceInfo& device,
    ProgressCallback  progress_cb
);

// Internal: AES-256 full-drive encryption (used in HDD Purge)
// key is randomly generated and never stored after this function returns
void encrypt_drive_aes256(const std::string& device_path, ProgressCallback progress_cb);

// Internal: Write random data from getrandom() syscall to all LBAs
void overwrite_random(const std::string& device_path, ProgressCallback progress_cb);

// ─────────────────────────────────────────────
// Firmware Deletion Mode
// ─────────────────────────────────────────────

// For SATA: ATA Security Erase Enhanced
// For NVMe: NVMe Sanitize (Block Erase or Crypto Erase)
// For drives with frozen security: falls back to Purge
WipeResult wipe_firmware(
    const DeviceInfo& device,
    ProgressCallback  progress_cb
);

} // namespace zerotrace
