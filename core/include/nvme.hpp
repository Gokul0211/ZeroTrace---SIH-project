#pragma once
#include "device.hpp"
#include <string>
#include <cstdint>

namespace zerotrace {
namespace nvme {

// ─────────────────────────────────────────────
// NVMe Admin Command Opcodes
// ─────────────────────────────────────────────

constexpr uint8_t NVME_ADMIN_IDENTIFY   = 0x06;
constexpr uint8_t NVME_ADMIN_GET_LOG    = 0x02;
constexpr uint8_t NVME_ADMIN_SANITIZE   = 0x84;
constexpr uint8_t NVME_ADMIN_FORMAT_NVM = 0x80;

// Sanitize Action values (SANACT field in CDW10)
constexpr uint8_t NVME_SANITIZE_CRYPTO_ERASE = 0x04;  // Fastest — key destruction
constexpr uint8_t NVME_SANITIZE_BLOCK_ERASE  = 0x02;  // Physical block erase
constexpr uint8_t NVME_SANITIZE_OVERWRITE     = 0x03;  // Pattern overwrite

// Sanitize Status log page ID
constexpr uint8_t NVME_LOG_SANITIZE_STATUS = 0x81;

// ─────────────────────────────────────────────
// NVMe Sanitize Status Log Page
// ─────────────────────────────────────────────

struct NVMeSanitizeLog {
    uint16_t sprog;     // Sanitize Progress (0x0000 = not started, 0xFFFF = complete)
    uint16_t sstat;     // Sanitize Status
    // sstat bits [2:0]:
    //   0x0 = Never been sanitized or no sanitize in progress
    //   0x1 = Sanitize in progress
    //   0x2 = Last sanitize completed successfully
    //   0x3 = Last sanitize failed
    uint32_t scdw10;    // Sanitize CDW10 (last sanitize command params)
    uint32_t eto;       // Estimated Time for Overwrite
    uint32_t etbe;      // Estimated Time for Block Erase
    uint32_t etce;      // Estimated Time for Crypto Erase
    uint32_t etond;     // Estimated Time for Overwrite (no-deallocate)
    uint32_t etbend;    // Estimated Time for Block Erase (no-deallocate)
    uint32_t etcend;    // Estimated Time for Crypto Erase (no-deallocate)
};

// ─────────────────────────────────────────────
// NVMe Identify Controller data (partial)
// ─────────────────────────────────────────────

struct NVMeIdentifyController {
    uint16_t vid;       // PCI Vendor ID
    uint16_t ssvid;     // Subsystem Vendor ID
    char     sn[20];    // Serial Number
    char     mn[40];    // Model Number
    char     fr[8];     // Firmware Revision
    uint8_t  rab;       // Recommended Arbitration Burst
    uint8_t  ieee[3];   // IEEE OUI Identifier
    uint8_t  cmic;      // Controller Multi-Path I/O
    uint8_t  mdts;      // Maximum Data Transfer Size
    uint8_t  sanicap;   // Sanitize Capabilities (byte 328)
    // sanicap bits:
    //   bit 0 = Crypto Erase supported
    //   bit 1 = Block Erase supported
    //   bit 2 = Overwrite supported
};

// ─────────────────────────────────────────────
// Function Declarations
// ─────────────────────────────────────────────

// Open NVMe character device — returns fd
// NVMe char device is at /dev/nvme0, /dev/nvme1, etc. (NOT /dev/nvme0n1)
int open_nvme_char_device(const std::string& nvme_char_path);

// Read NVMe controller identify data
NVMeIdentifyController read_identify(int fd);

// Issue NVMe Sanitize command
// action: one of NVME_SANITIZE_CRYPTO_ERASE, BLOCK_ERASE, OVERWRITE
void issue_sanitize(int fd, uint8_t action);

// Poll sanitize status log until complete or error
// Calls progress_cb every poll_interval_seconds
// Throws on sanitize failure
void poll_sanitize_status(int fd, ProgressCallback progress_cb, int poll_interval_seconds = 5);

// Issue NVMe Format NVM with optional crypto erase (ses=2)
void format_nvm(int fd, uint8_t ses = 0);

// Read sanitize log page
NVMeSanitizeLog read_sanitize_log(int fd);

// Scan NVMe device and fill DeviceInfo
DeviceInfo scan_nvme_device(const std::string& nvme_ns_path);

// Convert namespace device path to char device path
// e.g. /dev/nvme0n1 → /dev/nvme0
std::string ns_to_char_device(const std::string& ns_path);

} // namespace nvme
} // namespace zerotrace
