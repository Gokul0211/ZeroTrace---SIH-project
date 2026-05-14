#include "wipe.hpp"
#include "ata.hpp"
#include <fcntl.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <linux/fs.h>
#include <cstring>
#include <stdexcept>
#include <ctime>
#include <openssl/sha.h>
#include <cstdlib>

namespace zerotrace {

static std::string compute_sha256_first_mb(const std::string& path) {
    int fd = open(path.c_str(), O_RDONLY | O_DIRECT);
    if (fd < 0) return "unavailable";

    const size_t MB = 1024 * 1024;
    // O_DIRECT requires aligned memory
    uint8_t* buf = static_cast<uint8_t*>(aligned_alloc(512, MB));
    if (!buf) {
        close(fd);
        return "unavailable";
    }

    ssize_t n = read(fd, buf, MB);
    close(fd);

    if (n <= 0) {
        free(buf);
        return "unavailable";
    }

    unsigned char hash[SHA256_DIGEST_LENGTH];
    SHA256(buf, n, hash);
    free(buf);

    char hex[SHA256_DIGEST_LENGTH * 2 + 1];
    for (int i = 0; i < SHA256_DIGEST_LENGTH; i++) {
        sprintf(hex + i * 2, "%02x", hash[i]);
    }
    return std::string(hex);
}

std::string hash_first_mb(const std::string& device_path) {
    return compute_sha256_first_mb(device_path);
}

DeviceInfo prepare_device_for_wipe(const DeviceInfo& info) {
    DeviceInfo updated = info;

    if (info.type == DriveType::SSD_NVME) {
        // NVMe has no HPA/DCO — nothing to prepare
        return updated;
    }

    int fd = ata::open_device(info.device_path);

    try {
        // Step 1: Restore DCO if modified
        if (info.hidden.dco_modification_present) {
            ata::restore_dco(fd);
            updated.hidden.dco_modification_present = false;
        }

        // Step 2: Remove HPA if present
        if (info.hidden.hpa_detected) {
            uint64_t native = ata::read_native_max_lba(fd);
            ata::remove_hpa(fd, native, true);
            updated.hidden.hpa_detected = false;
        }

        // Step 3: Re-read device size (may have grown after HPA/DCO removal)
        uint64_t new_size = 0;
        if (ioctl(fd, BLKGETSIZE64, &new_size) == 0) {
            updated.size_bytes = new_size;
            updated.size_gb    = static_cast<double>(new_size) / (1024.0 * 1024.0 * 1024.0);
            updated.total_lbas = new_size / updated.sector_size;
        }

    } catch (...) {
        close(fd);
        throw;
    }

    close(fd);
    return updated;
}

WipeResult wipe_clear(const DeviceInfo& device, ProgressCallback progress_cb) {
    WipeResult result;
    result.mode_used   = WipeMode::CLEAR;
    result.start_epoch = static_cast<uint64_t>(time(nullptr));

    // Pre-wipe hash (first 1MB)
    result.sha256_pre_wipe = hash_first_mb(device.device_path);

    // Prepare device (HPA/DCO removal)
    DeviceInfo prepared = prepare_device_for_wipe(device);
    result.hpa_removed  = device.hidden.hpa_detected && !prepared.hidden.hpa_detected;
    result.dco_restored = device.hidden.dco_modification_present && !prepared.hidden.dco_modification_present;

    // Open device for writing with O_DIRECT and O_SYNC
    int fd = open(prepared.device_path.c_str(), O_WRONLY | O_DIRECT | O_SYNC);
    if (fd < 0) {
        result.success = false;
        result.error_message = "Cannot open device for writing: " + std::string(strerror(errno));
        return result;
    }

    const size_t BLOCK_SIZE = 1024 * 1024;  // 1MB per write
    uint8_t* zero_buf = static_cast<uint8_t*>(aligned_alloc(512, BLOCK_SIZE));
    if (!zero_buf) {
        close(fd);
        result.success = false;
        result.error_message = "aligned_alloc failed";
        return result;
    }
    memset(zero_buf, 0x00, BLOCK_SIZE);

    uint64_t total_bytes = prepared.size_bytes;
    uint64_t written     = 0;

    while (written < total_bytes) {
        size_t to_write = std::min(static_cast<uint64_t>(BLOCK_SIZE), total_bytes - written);

        // O_DIRECT requires transfer size to be sector-aligned
        size_t aligned_write = (to_write / 512) * 512;
        if (aligned_write == 0) break;

        ssize_t n = write(fd, zero_buf, aligned_write);
        if (n < 0) {
            if (errno == EIO) {
                // I/O error — likely a bad sector. Log and skip.
                lseek64(fd, written + aligned_write, SEEK_SET);
                written += aligned_write;
                continue;
            }
            result.success       = false;
            result.error_message = "Write error at byte " + std::to_string(written) + ": " + strerror(errno);
            free(zero_buf);
            close(fd);
            return result;
        }

        written += n;

        if (progress_cb) {
            progress_cb(written, total_bytes, "Clear: zero-filling");
        }
    }

    free(zero_buf);

    // Ensure all data hits the platter/flash
    fsync(fd);
    close(fd);

    result.end_epoch            = static_cast<uint64_t>(time(nullptr));
    result.duration_seconds     = static_cast<uint32_t>(result.end_epoch - result.start_epoch);
    result.sha256_post_wipe     = hash_first_mb(device.device_path);
    result.success              = true;
    result.hidden_areas_covered = result.hpa_removed || result.dco_restored;

    return result;
}

} // namespace zerotrace
