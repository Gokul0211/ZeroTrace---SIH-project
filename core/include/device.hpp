#pragma once
#include <string>
#include <vector>
#include <cstdint>
#include <optional>
#include <functional>

namespace zerotrace {

// ─────────────────────────────────────────────
// Enumerations
// ─────────────────────────────────────────────

enum class DriveType {
    HDD,            // Magnetic, SATA
    SSD_SATA,       // Flash, SATA interface
    SSD_NVME,       // Flash, NVMe/PCIe interface
    USB_DRIVE,      // USB bridge — limited firmware access
    UNKNOWN
};

enum class WipeMode {
    CLEAR,              // Zero overwrite — NIST Clear
    PURGE,              // Crypto erase + random overwrite — NIST Purge
    FIRMWARE_DELETION   // ATA Secure Erase / NVMe Sanitize — NIST Purge
};

enum class HealthStatus {
    PASSED,
    WARNING,    // Some SMART attributes degraded but drive is functional
    FAILED,     // Drive has critical errors — wipe may not complete
    UNKNOWN
};

// ─────────────────────────────────────────────
// SMART Data
// ─────────────────────────────────────────────

struct SmartData {
    // Key SMART attributes
    uint32_t reallocated_sector_count  = 0;
    uint32_t pending_sector_count      = 0;
    uint32_t uncorrectable_sector_count= 0;
    uint32_t power_on_hours            = 0;
    uint32_t temperature_celsius       = 0;
    uint32_t wear_leveling_count       = 0;   // SSD-specific
    uint32_t total_lbas_written        = 0;   // SSD-specific

    HealthStatus overall_health  = HealthStatus::UNKNOWN;
    bool smart_supported         = false;
    bool smart_enabled           = false;
};

// ─────────────────────────────────────────────
// HPA / DCO Status
// ─────────────────────────────────────────────

struct HiddenAreaStatus {
    bool     hpa_detected             = false;
    uint64_t hpa_hidden_lbas          = 0;   // LBAs hidden by HPA
    uint64_t native_max_lba           = 0;   // Real max LBA (from READ NATIVE MAX)
    uint64_t reported_max_lba         = 0;   // What OS sees

    bool     dco_detected             = false;
    uint64_t dco_native_max_lba       = 0;   // Factory default from DCO IDENTIFY
    bool     dco_modification_present = false;

    bool     security_frozen          = false; // ATA security frozen — blocks Secure Erase
};

// ─────────────────────────────────────────────
// Main Device Info Struct
// ─────────────────────────────────────────────

struct DeviceInfo {
    // Identity
    std::string device_path;       // e.g. "/dev/sda", "/dev/nvme0n1"
    std::string model;
    std::string serial;
    std::string firmware_version;
    DriveType   type        = DriveType::UNKNOWN;

    // Geometry
    uint64_t total_lbas  = 0;
    uint32_t sector_size = 512;    // bytes per sector (512 or 4096)
    uint64_t size_bytes  = 0;      // total_lbas * sector_size
    double   size_gb     = 0.0;

    // Health
    SmartData        smart;
    HiddenAreaStatus hidden;

    // Feature support flags
    bool supports_ata_secure_erase          = false;
    bool supports_ata_secure_erase_enhanced = false;
    bool supports_nvme_sanitize             = false;
    bool supports_nvme_format               = false;
    bool supports_dco                       = false;
    bool supports_hpa                       = false;
    bool is_ssd                             = false;
};

// ─────────────────────────────────────────────
// Wipe Progress Callback
// ─────────────────────────────────────────────

// The TUI registers a callback here so it can update the progress bar
// without the core engine knowing anything about curses
using ProgressCallback = std::function<void(uint64_t bytes_done, uint64_t bytes_total, const std::string& stage)>;

// ─────────────────────────────────────────────
// Wipe Result
// ─────────────────────────────────────────────

struct WipeResult {
    bool      success       = false;
    WipeMode  mode_used     = WipeMode::CLEAR;
    std::string error_message;      // empty if success

    // Timing
    uint64_t start_epoch      = 0;
    uint64_t end_epoch        = 0;
    uint32_t duration_seconds = 0;

    // What was actually done
    bool        hpa_removed            = false;
    bool        dco_restored           = false;
    bool        hidden_areas_covered   = false;
    bool        firmware_command_used  = false;
    std::string firmware_command_name; // e.g. "ATA Secure Erase Enhanced"

    // Pre/post hashes — SHA-256 of first 1MB of device
    std::string sha256_pre_wipe;
    std::string sha256_post_wipe;
};

// ─────────────────────────────────────────────
// Entropy Result
// ─────────────────────────────────────────────

struct EntropyResult {
    double      entropy_bits       = 0.0;
    std::string state;             // "ZERO_FILL_CONFIRMED" / "RANDOM_FILL_CONFIRMED" / "FAILED" / "VERIFY_MANUALLY"
    bool        wipe_verified      = false;
    uint64_t    blocks_sampled     = 0;
    uint64_t    total_blocks       = 0;
    double      sample_coverage_pct= 0.0;
};

// ─────────────────────────────────────────────
// Free functions declared in device.cpp
// ─────────────────────────────────────────────

std::vector<std::string> enumerate_block_devices();
DriveType                detect_drive_type(const std::string& device_path);
uint64_t                 get_device_size(int fd);
uint32_t                 get_sector_size(int fd);

} // namespace zerotrace
