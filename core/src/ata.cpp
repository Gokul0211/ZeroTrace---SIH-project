#include "ata.hpp"
#include <fcntl.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <scsi/sg.h>          // SG_IO ioctl — install sg3-utils / libsgutils2-dev
#include <linux/hdreg.h>      // HDIO_DRIVE_TASK
#include <linux/fs.h>         // BLKGETSIZE64
#include <cstring>
#include <stdexcept>
#include <sstream>
#include <iomanip>
#include <cerrno>

namespace zerotrace {
namespace ata {

// ─────────────────────────────────────────────
// SG_IO ATA Passthrough Infrastructure
// ─────────────────────────────────────────────
//
// ATA commands are wrapped in SCSI CDB (Command Descriptor Block) using the
// SAT (SCSI/ATA Translation) standard.
// We use the 16-byte ATA PASS-THROUGH(16) CDB with SCSI opcode 0x85.

struct ATAPassthroughCmd {
    uint8_t  feature      = 0;
    uint8_t  sector_count = 0;
    uint8_t  lba_low      = 0;
    uint8_t  lba_mid      = 0;
    uint8_t  lba_high     = 0;
    uint8_t  device       = 0;
    uint8_t  command      = 0;
    bool     data_in      = true; // true = device→host (read), false = host→device (write)
    uint8_t* data         = nullptr;
    size_t   data_len     = 0;
};

// Execute an ATA command via SG_IO 16-byte ATA PASS-THROUGH(16).
// Throws std::runtime_error on ioctl failure or SCSI error.
static void execute_ata_cmd(int fd, const ATAPassthroughCmd& cmd) {
    uint8_t cdb[16] = {};
    cdb[0]  = 0x85;                                      // ATA PASS-THROUGH (16) opcode
    // PROTOCOL field bits [4:1]:
    //   4 = PIO Data-In (device→host)
    //   5 = PIO Data-Out (host→device)
    //   3 = Non-data
    uint8_t protocol = (cmd.data == nullptr) ? 3 :
                       (cmd.data_in ? 4 : 5);
    cdb[1]  = (protocol << 1);

    // EXTEND=0, OFF_LINE=0, CK_COND=0, T_TYPE=0
    // T_LEN: if data, use sector count (bits [1:0] = 10); otherwise 00
    // BYT_BLOK=1 (transfer count in 512-byte blocks), T_DIR based on data_in
    if (cmd.data != nullptr) {
        cdb[2] = 0x2e;   // T_LEN=2 (sector count), BYT_BLOK=1, T_DIR=data_in
    } else {
        cdb[2] = 0x20;   // Non-data
    }

    cdb[4]  = cmd.feature;
    cdb[6]  = cmd.sector_count;
    cdb[8]  = cmd.lba_low;
    cdb[10] = cmd.lba_mid;
    cdb[12] = cmd.lba_high;
    cdb[13] = cmd.device | 0xA0;   // Device register: LBA mode (bit 6) + obsolete bits
    cdb[14] = cmd.command;

    sg_io_hdr_t io_hdr   = {};
    uint8_t     sense_buf[32] = {};

    io_hdr.interface_id    = 'S';
    io_hdr.cmd_len         = sizeof(cdb);
    io_hdr.cmdp            = cdb;
    io_hdr.dxfer_direction = cmd.data_in ? SG_DXFER_FROM_DEV : SG_DXFER_TO_DEV;
    io_hdr.dxferp          = cmd.data;
    io_hdr.dxfer_len       = cmd.data ? static_cast<unsigned int>(cmd.data_len) : 0;
    io_hdr.sbp             = sense_buf;
    io_hdr.mx_sb_len       = sizeof(sense_buf);
    io_hdr.timeout         = 30000;  // 30 seconds (non-erase commands)

    if (ioctl(fd, SG_IO, &io_hdr) < 0) {
        throw std::runtime_error(
            std::string("SG_IO ioctl failed: ") + strerror(errno));
    }

    // 0x02 = CHECK CONDITION is normal for ATA passthrough (sense data carries ATA return registers)
    if (io_hdr.status && io_hdr.status != 0x02) {
        throw std::runtime_error(
            "SCSI command failed with status: " + std::to_string(io_hdr.status));
    }
}

// ─────────────────────────────────────────────
// Open Device
// ─────────────────────────────────────────────

int open_device(const std::string& path) {
    int fd = open(path.c_str(), O_RDWR | O_NONBLOCK);
    if (fd < 0) {
        throw std::runtime_error(
            "Cannot open " + path + ": " + strerror(errno) +
            " (are you root?)");
    }
    return fd;
}

// ─────────────────────────────────────────────
// ATA IDENTIFY DEVICE
// ─────────────────────────────────────────────

ATAIdentifyData read_identify(int fd) {
    ATAIdentifyData id_data = {};
    uint8_t buf[512] = {};

    ATAPassthroughCmd cmd = {};
    cmd.command      = ATA_CMD_IDENTIFY;
    cmd.data_in      = true;
    cmd.data         = buf;
    cmd.data_len     = 512;
    cmd.sector_count = 1;

    execute_ata_cmd(fd, cmd);
    memcpy(id_data.words, buf, 512);
    return id_data;
}

// ATA strings are byte-swapped ASCII — this corrects the byte order
static std::string extract_ata_string(const uint16_t* words, int start_word, int end_word) {
    std::string result;
    for (int w = start_word; w <= end_word; w++) {
        result += static_cast<char>(words[w] >> 8);    // High byte first
        result += static_cast<char>(words[w] & 0xFF);  // Then low byte
    }
    // Trim trailing spaces
    while (!result.empty() && result.back() == ' ') result.pop_back();
    return result;
}

std::string ATAIdentifyData::get_model() const {
    return extract_ata_string(words, 27, 46);
}

std::string ATAIdentifyData::get_serial() const {
    return extract_ata_string(words, 10, 19);
}

std::string ATAIdentifyData::get_firmware() const {
    return extract_ata_string(words, 23, 26);
}

uint64_t ATAIdentifyData::get_lba48_capacity() const {
    // Words 100-103 form a 64-bit LBA count in 48-bit LBA mode
    return (static_cast<uint64_t>(words[103]) << 48) |
           (static_cast<uint64_t>(words[102]) << 32) |
           (static_cast<uint64_t>(words[101]) << 16) |
            static_cast<uint64_t>(words[100]);
}

// ─────────────────────────────────────────────
// SMART Read
// ─────────────────────────────────────────────

SmartData read_smart(int fd) {
    SmartData smart = {};
    uint8_t buf[512] = {};

    ATAPassthroughCmd cmd = {};
    cmd.command      = ATA_CMD_SMART;
    cmd.feature      = ATA_SMART_FEATURE_READ_DATA;
    cmd.lba_mid      = ATA_SMART_LBA_MID;
    cmd.lba_high     = ATA_SMART_LBA_HIGH;
    cmd.data_in      = true;
    cmd.data         = buf;
    cmd.data_len     = 512;
    cmd.sector_count = 1;

    execute_ata_cmd(fd, cmd);

    // SMART attribute table starts at byte 2.
    // Each entry is 12 bytes: [id(1), flags(2), current(1), worst(1), raw(6), reserved(1)]
    for (int i = 0; i < 30; i++) {
        int     offset   = 2 + (i * 12);
        uint8_t attr_id  = buf[offset];
        if (attr_id == 0) continue;

        // Raw value: bytes 5-10 of entry (6 bytes), we read lowest 4 as uint32_t
        uint32_t raw_value =
              static_cast<uint32_t>(buf[offset + 5])
            | (static_cast<uint32_t>(buf[offset + 6]) <<  8)
            | (static_cast<uint32_t>(buf[offset + 7]) << 16)
            | (static_cast<uint32_t>(buf[offset + 8]) << 24);

        switch (attr_id) {
            case 0x05: smart.reallocated_sector_count   = raw_value; break;
            case 0xC5: smart.pending_sector_count       = raw_value; break;
            case 0xC6: smart.uncorrectable_sector_count = raw_value; break;
            case 0x09: smart.power_on_hours             = raw_value; break;
            case 0xC2: smart.temperature_celsius        = raw_value & 0xFF; break; // Low byte = temp
            case 0xBB: smart.wear_leveling_count        = raw_value; break;
            case 0xF1: smart.total_lbas_written         = raw_value; break;
            default: break;
        }
    }

    // SMART RETURN STATUS — check if drive signals threshold exceeded
    uint8_t status_buf[512] = {};
    ATAPassthroughCmd status_cmd = {};
    status_cmd.command      = ATA_CMD_SMART;
    status_cmd.feature      = ATA_SMART_FEATURE_RETURN_STATUS;
    status_cmd.lba_mid      = ATA_SMART_LBA_MID;
    status_cmd.lba_high     = ATA_SMART_LBA_HIGH;
    status_cmd.data_in      = true;
    status_cmd.data         = status_buf;
    status_cmd.data_len     = 512;
    status_cmd.sector_count = 1;
    execute_ata_cmd(fd, status_cmd);

    smart.smart_supported = true;
    smart.smart_enabled   = true;

    // Threshold-exceeded condition: drive returns LBA mid=0xF4, LBA high=0x2C
    // We check sense data CylLow/CylHigh in status_buf[9]/[10] (ATA register returns)
    bool threshold_exceeded = (status_buf[9] == 0xF4 && status_buf[10] == 0x2C);

    if (threshold_exceeded) {
        smart.overall_health = HealthStatus::FAILED;
    } else if (smart.reallocated_sector_count > 10 ||
               smart.pending_sector_count > 0 ||
               smart.uncorrectable_sector_count > 0) {
        smart.overall_health = HealthStatus::WARNING;
    } else {
        smart.overall_health = HealthStatus::PASSED;
    }

    return smart;
}

// ─────────────────────────────────────────────
// HPA Detection and Removal
// ─────────────────────────────────────────────

uint64_t read_reported_max_lba(int fd) {
    // The OS-visible size (already accounts for any HPA reduction)
    // BLKGETSIZE64 returns bytes; divide by 512 to get sectors
    uint64_t size = 0;
    if (ioctl(fd, BLKGETSIZE64, &size) < 0) {
        throw std::runtime_error(
            std::string("BLKGETSIZE64 failed: ") + strerror(errno));
    }
    return size / 512;
}

uint64_t read_native_max_lba(int fd) {
    // READ NATIVE MAX ADDRESS — returns physical max regardless of HPA.
    // Use HDIO_DRIVE_TASK to send the command and read back ATA task-file registers.
    uint8_t args[7] = {
        ATA_CMD_READ_MAX_ADDRESS,  // [0] command
        0,                          // [1] feature
        0,                          // [2] sector count
        0,                          // [3] LBA low  (sector number)
        ATA_SMART_LBA_MID,          // [4] LBA mid  — unused for this cmd, but required
        ATA_SMART_LBA_HIGH,         // [5] LBA high
        0x40                        // [6] device (LBA mode bit)
    };

    if (ioctl(fd, HDIO_DRIVE_TASK, args) < 0) {
        // HDIO_DRIVE_TASK unavailable on some kernels — fall back to reported
        return read_reported_max_lba(fd);
    }

    // args[3..6] are updated with task-file return values after command
    // For READ NATIVE MAX ADDRESS, result is a 28-bit LBA:
    // bits[7:0]   = sector number  (LBA low)
    // bits[15:8]  = cylinder low   (LBA mid)
    // bits[23:16] = cylinder high  (LBA high)
    // bits[27:24] = device[3:0]
    uint64_t lba =
          static_cast<uint64_t>(args[3])
        | (static_cast<uint64_t>(args[4]) <<  8)
        | (static_cast<uint64_t>(args[5]) << 16)
        | (static_cast<uint64_t>(args[6] & 0x0F) << 24);

    // If result is 0, fall back to reported (drive may not support 28-bit READ NATIVE MAX)
    return (lba == 0) ? read_reported_max_lba(fd) : lba;
}

void remove_hpa(int fd, uint64_t native_max_lba, bool persistent) {
    // SET MAX ADDRESS EXT (0x37) for persistent; SET MAX ADDRESS (0xF9) for volatile
    ATAPassthroughCmd cmd = {};
    cmd.command  = persistent ? ATA_CMD_SET_MAX_ADDRESS_EXT : ATA_CMD_SET_MAX_ADDRESS;
    // feature 0x01 = save to disk (persistent); 0x00 = volatile (resets on power cycle)
    cmd.feature  = persistent ? 0x01 : 0x00;
    // Pack native_max_lba into LBA registers (48-bit addressing for EXT variant)
    cmd.lba_low  = (native_max_lba >>  0) & 0xFF;
    cmd.lba_mid  = (native_max_lba >>  8) & 0xFF;
    cmd.lba_high = (native_max_lba >> 16) & 0xFF;
    cmd.device   = 0x40 | ((native_max_lba >> 24) & 0x0F);
    cmd.data     = nullptr;  // Non-data command

    execute_ata_cmd(fd, cmd);
}

// ─────────────────────────────────────────────
// DCO Detection and Restoration
// ─────────────────────────────────────────────

uint64_t read_dco_identify_lba(int fd) {
    uint8_t buf[512] = {};

    ATAPassthroughCmd cmd = {};
    cmd.command      = ATA_CMD_DCO_IDENTIFY;
    cmd.feature      = 0xC2;   // DCO IDENTIFY sub-command
    cmd.data_in      = true;
    cmd.data         = buf;
    cmd.data_len     = 512;
    cmd.sector_count = 1;

    execute_ata_cmd(fd, cmd);

    // DCO IDENTIFY response: max LBA at bytes 2-5, little-endian 32-bit
    uint64_t max_lba =
          static_cast<uint64_t>(buf[2])
        | (static_cast<uint64_t>(buf[3]) <<  8)
        | (static_cast<uint64_t>(buf[4]) << 16)
        | (static_cast<uint64_t>(buf[5]) << 24);

    return max_lba;
}

void restore_dco(int fd) {
    ATAPassthroughCmd cmd = {};
    cmd.command = ATA_CMD_DCO_RESTORE;
    cmd.feature = 0xC0;  // DCO RESTORE sub-command
    cmd.data    = nullptr;

    execute_ata_cmd(fd, cmd);
}

// ─────────────────────────────────────────────
// ATA Security (Secure Erase)
// ─────────────────────────────────────────────

bool is_security_frozen(int fd) {
    ATAIdentifyData id = read_identify(fd);
    return id.security_frozen();
}

bool try_unfreeze_security(int fd) {
    // S3 suspend-to-RAM causes some BIOSes to unfreeze ATA security on resume.
    // We trigger this by writing "mem" to /sys/power/state.
    int state_fd = open("/sys/power/state", O_WRONLY);
    if (state_fd < 0) return false;

    const char* state = "mem";
    write(state_fd, state, 3);
    close(state_fd);

    sleep(3);  // Allow system to suspend and resume

    return !is_security_frozen(fd);
}

void security_erase_prepare(int fd) {
    ATAPassthroughCmd cmd = {};
    cmd.command = ATA_CMD_SECURITY_ERASE_PREP;
    cmd.data    = nullptr;
    execute_ata_cmd(fd, cmd);
}

void security_erase_unit(int fd, bool enhanced) {
    // SECURITY ERASE UNIT requires a 512-byte password block sent to the drive.
    // Byte 0:    identifier (0 = user password, 1 = master password)
    // Bytes 2-33: password field (all zeros = NULL password matching ERASE PREPARE state)
    // Bit 1 of byte 0: enhanced erase flag
    uint8_t password_block[512] = {};
    if (enhanced) {
        password_block[0] |= 0x02;   // Enhanced erase bit
    }

    // Build CDB manually with a 3-hour timeout (Secure Erase can take very long)
    uint8_t cdb[16] = {};
    cdb[0]  = 0x85;               // ATA PASS-THROUGH (16)
    cdb[1]  = (5 << 1);           // PROTOCOL = 5 (PIO Data-Out)
    cdb[2]  = 0x26;               // T_LEN=2, BYT_BLOK=1, T_DIR=0 (to device)
    cdb[4]  = enhanced ? 0x02 : 0x00;  // feature (enhanced flag)
    cdb[6]  = 1;                  // sector count
    cdb[13] = 0xA0;               // device register
    cdb[14] = ATA_CMD_SECURITY_ERASE_UNIT;

    sg_io_hdr_t io_hdr   = {};
    uint8_t     sense_buf[32] = {};

    io_hdr.interface_id    = 'S';
    io_hdr.cmd_len         = sizeof(cdb);
    io_hdr.cmdp            = cdb;
    io_hdr.dxfer_direction = SG_DXFER_TO_DEV;
    io_hdr.dxferp          = password_block;
    io_hdr.dxfer_len       = 512;
    io_hdr.sbp             = sense_buf;
    io_hdr.mx_sb_len       = sizeof(sense_buf);
    io_hdr.timeout         = 10800000;   // 3 hours in milliseconds

    if (ioctl(fd, SG_IO, &io_hdr) < 0) {
        throw std::runtime_error(
            std::string("ATA Security Erase UNIT ioctl failed: ") + strerror(errno));
    }
}

// ─────────────────────────────────────────────
// Full Device Scan
// ─────────────────────────────────────────────

DeviceInfo scan_device(const std::string& device_path) {
    DeviceInfo info;
    info.device_path = device_path;
    info.type        = detect_drive_type(device_path);

    int fd = open_device(device_path);

    try {
        ATAIdentifyData id = read_identify(fd);

        info.model            = id.get_model();
        info.serial           = id.get_serial();
        info.firmware_version = id.get_firmware();
        info.is_ssd           = id.is_ssd();
        info.total_lbas       = id.get_lba48_capacity();

        // Read actual sector size (may be 4096 for Advanced Format drives)
        info.sector_size = get_sector_size(fd);
        if (info.sector_size == 0) info.sector_size = 512;

        info.size_bytes = info.total_lbas * info.sector_size;
        info.size_gb    = static_cast<double>(info.size_bytes) / (1024.0 * 1024.0 * 1024.0);

        // ATA feature support flags
        info.supports_ata_secure_erase          = (id.words[82] >> 1) & 1;
        info.supports_ata_secure_erase_enhanced = (id.words[128] >> 5) & 1;
        info.supports_hpa                       = (id.words[82] >> 10) & 1;
        info.supports_dco                       = true;  // Attempt and verify

        // SMART
        if (id.supports_smart()) {
            try {
                info.smart = read_smart(fd);
            } catch (...) {
                // SMART read failure is non-fatal; mark as unsupported
                info.smart.smart_supported = false;
                info.smart.overall_health  = HealthStatus::UNKNOWN;
            }
        }

        // HPA detection
        if (info.supports_hpa) {
            uint64_t native   = read_native_max_lba(fd);
            uint64_t reported = read_reported_max_lba(fd);
            info.hidden.native_max_lba    = native;
            info.hidden.reported_max_lba  = reported;
            info.hidden.hpa_detected      = (native > reported);
            info.hidden.hpa_hidden_lbas   = (native > reported) ? (native - reported) : 0;
        }

        // DCO detection
        try {
            uint64_t dco_lba = read_dco_identify_lba(fd);
            info.hidden.dco_native_max_lba      = dco_lba;
            info.hidden.dco_detected            = true;
            info.hidden.dco_modification_present= (dco_lba != 0 && dco_lba != info.total_lbas);
        } catch (...) {
            info.hidden.dco_detected = false;
            info.supports_dco        = false;
        }

        // Security frozen status
        info.hidden.security_frozen = id.security_frozen();

    } catch (...) {
        close(fd);
        throw;
    }

    close(fd);
    return info;
}

} // namespace ata
} // namespace zerotrace
