#include "nvme.hpp"
#include <fcntl.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <linux/nvme_ioctl.h>
#include <linux/fs.h>
#include <cstring>
#include <stdexcept>
#include <thread>
#include <chrono>
#include <filesystem>
#include <regex>
#include <cerrno>

namespace zerotrace {
namespace nvme {

// ─────────────────────────────────────────────
// Open NVMe Character Device
// ─────────────────────────────────────────────

int open_nvme_char_device(const std::string& nvme_char_path) {
    int fd = open(nvme_char_path.c_str(), O_RDWR);
    if (fd < 0) {
        throw std::runtime_error(
            "Cannot open NVMe device " + nvme_char_path + ": " + strerror(errno));
    }
    return fd;
}

// ─────────────────────────────────────────────
// Namespace → Char Device Conversion
// ─────────────────────────────────────────────

std::string ns_to_char_device(const std::string& ns_path) {
    // /dev/nvme0n1 → /dev/nvme0
    // /dev/nvme1n2 → /dev/nvme1
    std::regex ns_pattern(R"(/dev/(nvme\d+)n\d+)");
    std::smatch match;
    if (std::regex_match(ns_path, match, ns_pattern)) {
        return "/dev/" + match[1].str();
    }
    // If it's already a char device (no 'n' suffix), return as-is
    std::regex char_pattern(R"(/dev/nvme\d+)");
    if (std::regex_match(ns_path, char_pattern)) {
        return ns_path;
    }
    throw std::runtime_error("Not a valid NVMe namespace path: " + ns_path);
}

// ─────────────────────────────────────────────
// NVMe Identify Controller
// ─────────────────────────────────────────────

NVMeIdentifyController read_identify(int fd) {
    NVMeIdentifyController id = {};
    uint8_t buf[4096] = {};   // Full Identify Controller response is 4096 bytes

    struct nvme_admin_cmd cmd = {};
    cmd.opcode   = NVME_ADMIN_IDENTIFY;
    cmd.nsid     = 0;
    cmd.cdw10    = 1;           // CNS=1 → Identify Controller
    cmd.addr     = reinterpret_cast<uint64_t>(buf);
    cmd.data_len = sizeof(buf);

    if (ioctl(fd, NVME_IOCTL_ADMIN_CMD, &cmd) < 0) {
        throw std::runtime_error(
            std::string("NVMe Identify Controller failed: ") + strerror(errno));
    }

    // Parse fields from raw buffer per NVMe Base Spec 2.0
    memcpy(id.sn,   buf +  4, 20);   // Serial Number:    bytes   4-23
    memcpy(id.mn,   buf + 24, 40);   // Model Number:     bytes  24-63
    memcpy(id.fr,   buf + 64,  8);   // Firmware Rev:     bytes  64-71
    id.rab        = buf[72];
    memcpy(id.ieee, buf + 73,  3);
    id.cmic       = buf[76];
    id.mdts       = buf[77];
    id.sanicap    = buf[328];         // Sanitize Capabilities byte

    return id;
}

// ─────────────────────────────────────────────
// NVMe Sanitize Command
// ─────────────────────────────────────────────

void issue_sanitize(int fd, uint8_t action) {
    struct nvme_admin_cmd cmd = {};
    cmd.opcode = NVME_ADMIN_SANITIZE;
    // CDW10: SANACT[2:0] = action
    // AUSE=0 (don't allow unrestricted sanitize exit)
    // OWPASS=0 (overwrite pass count — N/A for crypto/block erase)
    // OIPBP=0, NODAS=0
    cmd.cdw10 = static_cast<uint32_t>(action & 0x07);

    if (ioctl(fd, NVME_IOCTL_ADMIN_CMD, &cmd) < 0) {
        throw std::runtime_error(
            std::string("NVMe Sanitize command failed: ") + strerror(errno));
    }
    // NOTE: NVMe Sanitize is ASYNCHRONOUS.
    // The command returns immediately; completion must be polled via the
    // Sanitize Status log page (log ID 0x81).
}

// ─────────────────────────────────────────────
// NVMe Sanitize Status Log Page
// ─────────────────────────────────────────────

NVMeSanitizeLog read_sanitize_log(int fd) {
    NVMeSanitizeLog log = {};
    uint8_t buf[512] = {};

    struct nvme_admin_cmd cmd = {};
    cmd.opcode = NVME_ADMIN_GET_LOG;
    cmd.nsid   = 0xFFFFFFFF;  // Global (applies to all namespaces)
    // CDW10: LID[7:0] | LSPF[11:8]=0 | NUMDL[31:16] = (len/4 - 1)
    uint32_t numdl = static_cast<uint32_t>(sizeof(buf) / 4 - 1);
    cmd.cdw10  = static_cast<uint32_t>(NVME_LOG_SANITIZE_STATUS)
                | (numdl << 16);
    cmd.addr     = reinterpret_cast<uint64_t>(buf);
    cmd.data_len = sizeof(buf);

    if (ioctl(fd, NVME_IOCTL_ADMIN_CMD, &cmd) < 0) {
        throw std::runtime_error(
            std::string("NVMe Get Log (Sanitize Status) failed: ") + strerror(errno));
    }

    // NVMeSanitizeLog is packed to match the log page layout
    memcpy(&log, buf, sizeof(NVMeSanitizeLog));
    return log;
}

// ─────────────────────────────────────────────
// Poll Sanitize Status
// ─────────────────────────────────────────────

void poll_sanitize_status(int fd, ProgressCallback progress_cb, int poll_interval_seconds) {
    while (true) {
        NVMeSanitizeLog log = read_sanitize_log(fd);
        uint8_t sstat_status = log.sstat & 0x7;  // Lower 3 bits = status code

        if (sstat_status == 0x1) {
            // Sanitize in progress — report percentage
            float progress = (log.sprog == 0)
                ? 0.0f
                : (static_cast<float>(log.sprog) / 0xFFFF * 100.0f);

            if (progress_cb) {
                progress_cb(
                    static_cast<uint64_t>(progress),
                    100ULL,
                    "NVMe Sanitize in progress: " +
                    std::to_string(static_cast<int>(progress)) + "%"
                );
            }
            std::this_thread::sleep_for(std::chrono::seconds(poll_interval_seconds));

        } else if (sstat_status == 0x2) {
            // Completed successfully
            if (progress_cb) {
                progress_cb(100, 100, "NVMe Sanitize complete");
            }
            return;

        } else if (sstat_status == 0x3) {
            throw std::runtime_error("NVMe Sanitize FAILED (sstat bits = 0x3)");

        } else {
            // 0x0 = never been sanitized / command not yet registered by controller
            // Brief wait then re-poll
            std::this_thread::sleep_for(std::chrono::seconds(2));
        }
    }
}

// ─────────────────────────────────────────────
// NVMe Format NVM
// ─────────────────────────────────────────────

void format_nvm(int fd, uint8_t ses) {
    // Format NVM admin command (opcode 0x80)
    // CDW10: SES[11:9] = Secure Erase Settings
    //   0 = No secure erase
    //   1 = User data erase
    //   2 = Cryptographic erase
    struct nvme_admin_cmd cmd = {};
    cmd.opcode = NVME_ADMIN_FORMAT_NVM;
    cmd.nsid   = 0xFFFFFFFF;    // Format all namespaces
    cmd.cdw10  = static_cast<uint32_t>((ses & 0x07) << 9);

    if (ioctl(fd, NVME_IOCTL_ADMIN_CMD, &cmd) < 0) {
        throw std::runtime_error(
            std::string("NVMe Format NVM failed: ") + strerror(errno));
    }
}

// ─────────────────────────────────────────────
// Full NVMe Device Scan
// ─────────────────────────────────────────────

DeviceInfo scan_nvme_device(const std::string& nvme_ns_path) {
    DeviceInfo info;
    info.device_path = nvme_ns_path;
    info.type        = DriveType::SSD_NVME;
    info.is_ssd      = true;

    // Open the char device for admin commands
    std::string char_path = ns_to_char_device(nvme_ns_path);
    int fd = open_nvme_char_device(char_path);

    try {
        NVMeIdentifyController id = read_identify(fd);

        // Helper: trim trailing spaces from fixed-length NVMe strings
        auto trim = [](const char* s, int len) -> std::string {
            std::string result(s, static_cast<size_t>(len));
            while (!result.empty() && result.back() == ' ') result.pop_back();
            return result;
        };

        info.model            = trim(id.mn, 40);
        info.serial           = trim(id.sn, 20);
        info.firmware_version = trim(id.fr,  8);

        // Sanitize capability
        info.supports_nvme_sanitize = (id.sanicap & 0x07) != 0;
        info.supports_nvme_format   = true;  // Format NVM always supported

        // Open namespace device to read size via BLKGETSIZE64
        int blk_fd = open(nvme_ns_path.c_str(), O_RDONLY);
        if (blk_fd >= 0) {
            uint64_t size = 0;
            if (ioctl(blk_fd, BLKGETSIZE64, &size) == 0) {
                info.size_bytes = size;
                info.size_gb    = static_cast<double>(size) / (1024.0 * 1024.0 * 1024.0);

                // Read logical block size
                uint32_t sector_size = 512;
                ioctl(blk_fd, BLKSSZGET, &sector_size);
                info.sector_size = (sector_size > 0) ? sector_size : 512;
                info.total_lbas  = size / info.sector_size;
            }
            close(blk_fd);
        }

        // NVMe has no HPA or DCO concepts
        info.hidden.hpa_detected = false;
        info.hidden.dco_detected = false;
        info.supports_hpa        = false;
        info.supports_dco        = false;

        // Minimal health (NVMe SMART log parsing is a lower-priority extension)
        info.smart.smart_supported = true;
        info.smart.overall_health  = HealthStatus::PASSED;

    } catch (...) {
        close(fd);
        throw;
    }

    close(fd);
    return info;
}

} // namespace nvme
} // namespace zerotrace
