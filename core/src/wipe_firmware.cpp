#include "wipe.hpp"
#include "ata.hpp"
#include "nvme.hpp"
#include <unistd.h>
#include <stdexcept>
#include <ctime>

namespace zerotrace {

WipeResult wipe_firmware(const DeviceInfo& device, ProgressCallback progress_cb) {
    WipeResult result;
    result.mode_used   = WipeMode::FIRMWARE_DELETION;
    result.start_epoch = static_cast<uint64_t>(time(nullptr));
    result.sha256_pre_wipe = hash_first_mb(device.device_path);

    DeviceInfo prepared = prepare_device_for_wipe(device);
    result.hpa_removed  = device.hidden.hpa_detected && !prepared.hidden.hpa_detected;
    result.dco_restored = device.hidden.dco_modification_present && !prepared.hidden.dco_modification_present;

    if (device.type == DriveType::SSD_NVME) {
        // NVMe Path: Sanitize (Block Erase or Crypto Erase)
        std::string char_dev = nvme::ns_to_char_device(device.device_path);
        int fd = nvme::open_nvme_char_device(char_dev);

        nvme::NVMeIdentifyController id = nvme::read_identify(fd);
        uint8_t action;

        if (id.sanicap & 0x01) {
            action = nvme::NVME_SANITIZE_CRYPTO_ERASE;
            result.firmware_command_name = "NVMe Sanitize (Crypto Erase)";
        } else if (id.sanicap & 0x02) {
            action = nvme::NVME_SANITIZE_BLOCK_ERASE;
            result.firmware_command_name = "NVMe Sanitize (Block Erase)";
        } else if (id.sanicap & 0x04) {
            action = nvme::NVME_SANITIZE_OVERWRITE;
            result.firmware_command_name = "NVMe Sanitize (Overwrite)";
        } else {
            close(fd);
            throw std::runtime_error("NVMe device does not support Sanitize");
        }

        nvme::issue_sanitize(fd, action);
        nvme::poll_sanitize_status(fd, progress_cb, 5);
        close(fd);

        result.firmware_command_used = true;
        result.hidden_areas_covered  = true;

    } else if (device.type == DriveType::SSD_SATA || device.type == DriveType::HDD) {
        // ATA Path: Secure Erase Enhanced
        int fd = ata::open_device(device.device_path);

        if (!ata::is_security_frozen(fd)) {
            ata::security_erase_prepare(fd);
            
            // Prefer Enhanced erase if supported, otherwise normal erase
            bool use_enhanced = device.supports_ata_secure_erase_enhanced;
            ata::security_erase_unit(fd, use_enhanced);
            
            result.firmware_command_name = use_enhanced ? 
                "ATA Secure Erase Enhanced" : "ATA Secure Erase Normal";
            result.firmware_command_used = true;
            result.hidden_areas_covered  = use_enhanced;
        } else {
            // Security is frozen — try S3 unfreeze
            bool unfrozen = ata::try_unfreeze_security(fd);
            if (!unfrozen) {
                close(fd);
                // Fallback to Purge if firmware deletion is impossible due to frozen state
                if (progress_cb) {
                    progress_cb(0, 100, "Security frozen — falling back to Purge mode");
                }
                return wipe_purge(device, progress_cb);
            } else {
                close(fd);
                fd = ata::open_device(device.device_path);
                
                ata::security_erase_prepare(fd);
                bool use_enhanced = device.supports_ata_secure_erase_enhanced;
                ata::security_erase_unit(fd, use_enhanced);
                
                result.firmware_command_name = use_enhanced ? 
                    "ATA Secure Erase Enhanced (after unfreeze)" : "ATA Secure Erase Normal (after unfreeze)";
                result.firmware_command_used = true;
                result.hidden_areas_covered  = use_enhanced;
            }
        }
        if (fd >= 0) close(fd);

    } else {
        throw std::runtime_error("Firmware Deletion not supported on this device type");
    }

    result.end_epoch        = static_cast<uint64_t>(time(nullptr));
    result.duration_seconds = static_cast<uint32_t>(result.end_epoch - result.start_epoch);
    result.sha256_post_wipe = hash_first_mb(device.device_path);
    result.success          = true;

    return result;
}

} // namespace zerotrace
