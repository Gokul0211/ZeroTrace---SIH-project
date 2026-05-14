#pragma once
#include "device.hpp"
#include <string>
#include <cstdint>

namespace zerotrace {
namespace ata {

// ─────────────────────────────────────────────
// ATA Command Opcodes (needed for SG_IO passthrough)
// ─────────────────────────────────────────────

constexpr uint8_t ATA_CMD_IDENTIFY             = 0xEC;
constexpr uint8_t ATA_CMD_SMART                = 0xB0;
constexpr uint8_t ATA_CMD_SECURITY_ERASE_PREP  = 0xF3;
constexpr uint8_t ATA_CMD_SECURITY_ERASE_UNIT  = 0xF4;
constexpr uint8_t ATA_CMD_READ_MAX_ADDRESS     = 0xF8;  // 28-bit
constexpr uint8_t ATA_CMD_READ_MAX_ADDRESS_EXT = 0x27;  // 48-bit LBA
constexpr uint8_t ATA_CMD_SET_MAX_ADDRESS      = 0xF9;
constexpr uint8_t ATA_CMD_SET_MAX_ADDRESS_EXT  = 0x37;
constexpr uint8_t ATA_CMD_DCO_IDENTIFY         = 0xB1;
constexpr uint8_t ATA_CMD_DCO_RESTORE          = 0xB1;
constexpr uint8_t ATA_SMART_FEATURE_READ_DATA      = 0xD0;
constexpr uint8_t ATA_SMART_FEATURE_RETURN_STATUS  = 0xDA;

// ATA SMART LBA mid/high magic values
constexpr uint8_t ATA_SMART_LBA_MID  = 0x4F;
constexpr uint8_t ATA_SMART_LBA_HIGH = 0xC2;

// ─────────────────────────────────────────────
// Raw ATA IDENTIFY data (first 512 bytes from drive)
// ─────────────────────────────────────────────

struct ATAIdentifyData {
    uint16_t words[256];

    // Helper methods to extract fields
    std::string get_model()    const;       // words[27-46], byte-swapped ASCII
    std::string get_serial()   const;       // words[10-19]
    std::string get_firmware() const;       // words[23-26]
    uint64_t    get_lba48_capacity() const; // words[100-103]
    uint16_t    get_security_status() const { return words[128]; }
    bool supports_48bit_lba() const { return (words[83]  >> 10) & 1; }
    bool supports_smart()     const { return (words[82]  >>  0) & 1; }
    bool is_ssd()             const { return (words[217] ==  1); }   // Nominal media rotation rate = SSD
    bool security_frozen()    const { return (words[128] >>  3) & 1; }
    bool security_enabled()   const { return (words[128] >>  1) & 1; }
};

// ─────────────────────────────────────────────
// Function Declarations
// ─────────────────────────────────────────────

// Open a raw block device for ATA passthrough — returns fd or throws
// Caller is responsible for close(fd)
int open_device(const std::string& path);

// Read 512-byte ATA IDENTIFY DEVICE response
ATAIdentifyData read_identify(int fd);

// Read SMART data and parse into SmartData struct
SmartData read_smart(int fd);

// Read current max LBA (what OS sees — may be reduced by HPA)
uint64_t read_reported_max_lba(int fd);

// Read NATIVE max LBA (true physical capacity ignoring HPA)
uint64_t read_native_max_lba(int fd);

// Read DCO IDENTIFY to check if DCO has modified the drive config
// Returns max LBA as reported by DCO IDENTIFY
uint64_t read_dco_identify_lba(int fd);

// Remove HPA by setting max address to native max
// persistent=true means the change survives power cycle
// WARNING: only call after confirming HPA is present
void remove_hpa(int fd, uint64_t native_max_lba, bool persistent = true);

// Restore DCO to factory defaults
// WARNING: permanent, irreversible on some drives
void restore_dco(int fd);

// Issue ATA SECURITY ERASE PREPARE (must precede SECURITY ERASE UNIT)
void security_erase_prepare(int fd);

// Issue ATA SECURITY ERASE UNIT
// enhanced=true erases HPA, reallocated sectors, etc. (NIST Purge)
// enhanced=false is normal erase (NIST Clear for HDDs)
void security_erase_unit(int fd, bool enhanced = true);

// Check if ATA security is frozen (blocks Secure Erase)
bool is_security_frozen(int fd);

// Attempt to unfreeze by triggering S3 suspend/resume
// Returns true if unfreeze succeeded
bool try_unfreeze_security(int fd);

// Full device scan — fills in DeviceInfo including SMART, HPA, DCO
DeviceInfo scan_device(const std::string& device_path);

} // namespace ata
} // namespace zerotrace
