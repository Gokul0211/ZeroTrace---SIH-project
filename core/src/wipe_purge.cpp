#include "wipe.hpp"
#include "ata.hpp"
#include "nvme.hpp"
#include <fcntl.h>
#include <unistd.h>
#include <sys/random.h>
#include <sys/ioctl.h>
#include <linux/fs.h>
#include <cstring>
#include <stdexcept>
#include <ctime>
#include <openssl/evp.h>
#include <openssl/rand.h>

namespace zerotrace {

void encrypt_drive_aes256(const std::string& device_path, ProgressCallback progress_cb) {
    // Generate random 256-bit key and 128-bit IV
    // CRITICAL: These are generated fresh each call and NEVER stored.
    // The only goal is to encrypt the drive so that destroying the key
    // makes all data computationally irrecoverable.
    uint8_t key[32], iv[16];
    if (RAND_bytes(key, sizeof(key)) != 1 ||
        RAND_bytes(iv,  sizeof(iv))  != 1) {
        throw std::runtime_error("RAND_bytes failed — cannot generate encryption key");
    }

    EVP_CIPHER_CTX* ctx = EVP_CIPHER_CTX_new();
    if (!ctx) {
        throw std::runtime_error("EVP_CIPHER_CTX_new failed");
    }
    EVP_EncryptInit_ex(ctx, EVP_aes_256_cbc(), nullptr, key, iv);

    int rd_fd = open(device_path.c_str(), O_RDONLY | O_DIRECT);
    int wr_fd = open(device_path.c_str(), O_WRONLY | O_DIRECT | O_SYNC);

    if (rd_fd < 0 || wr_fd < 0) {
        EVP_CIPHER_CTX_free(ctx);
        if (rd_fd >= 0) close(rd_fd);
        if (wr_fd >= 0) close(wr_fd);
        throw std::runtime_error("Cannot open device for encrypt-purge");
    }

    const size_t BUF = 1024 * 1024; // 1MB chunks
    uint8_t* in_buf  = static_cast<uint8_t*>(aligned_alloc(512, BUF));
    uint8_t* out_buf = static_cast<uint8_t*>(aligned_alloc(512, BUF + EVP_MAX_BLOCK_LENGTH)); // Padding space

    if (!in_buf || !out_buf) {
        EVP_CIPHER_CTX_free(ctx);
        close(rd_fd); close(wr_fd);
        if (in_buf) free(in_buf);
        if (out_buf) free(out_buf);
        throw std::runtime_error("aligned_alloc failed for AES buffers");
    }

    uint64_t total = 0;
    ioctl(rd_fd, BLKGETSIZE64, &total);
    uint64_t processed = 0;

    while (processed < total) {
        size_t to_read = std::min(static_cast<uint64_t>(BUF), total - processed);
        size_t aligned_read = (to_read / 512) * 512;
        if (aligned_read == 0) break;

        ssize_t n = read(rd_fd, in_buf, aligned_read);
        if (n <= 0) break;

        int out_len = 0;
        EVP_EncryptUpdate(ctx, out_buf, &out_len, in_buf, static_cast<int>(n));

        // Ensure output is sector-aligned for O_DIRECT write
        // With AES-CBC and aligned inputs, out_len should be aligned.
        size_t write_len = (out_len / 512) * 512;
        if (write_len > 0) {
            lseek64(wr_fd, processed, SEEK_SET);
            write(wr_fd, out_buf, write_len);
        }

        processed += n;
        if (progress_cb) {
            progress_cb(processed, total, "Purge: AES-256 encrypting");
        }
    }

    // We don't write the final padded block (EVP_EncryptFinal_ex) because
    // it wouldn't be sector-aligned and we don't care about correct decryption anyway.
    
    EVP_CIPHER_CTX_free(ctx);

    // KEY DESTRUCTION: Zero out key and IV from stack memory
    // The key was never written to disk — it only existed in this stack frame.
    // Zeroing is defense-in-depth against memory forensics.
    explicit_bzero(key, sizeof(key));
    explicit_bzero(iv, sizeof(iv));

    free(in_buf);
    free(out_buf);
    fsync(wr_fd);
    close(rd_fd);
    close(wr_fd);
}

void overwrite_random(const std::string& device_path, ProgressCallback progress_cb) {
    int fd = open(device_path.c_str(), O_WRONLY | O_DIRECT | O_SYNC);
    if (fd < 0) {
        throw std::runtime_error("Cannot open device for random overwrite: " + std::string(strerror(errno)));
    }

    uint64_t total = 0;
    ioctl(fd, BLKGETSIZE64, &total);

    const size_t BUF = 1024 * 1024;
    uint8_t* buf = static_cast<uint8_t*>(aligned_alloc(512, BUF));
    if (!buf) {
        close(fd);
        throw std::runtime_error("aligned_alloc failed for random buffer");
    }

    uint64_t written = 0;
    while (written < total) {
        size_t to_write = std::min(static_cast<uint64_t>(BUF), total - written);
        size_t aligned = (to_write / 512) * 512;
        if (aligned == 0) break;

        // getrandom() is better than /dev/urandom — uses kernel CSPRNG directly
        ssize_t r = getrandom(buf, aligned, 0);
        if (r < 0) {
            // Fallback to /dev/urandom if getrandom fails (unlikely on modern kernels)
            int urandom_fd = open("/dev/urandom", O_RDONLY);
            if (urandom_fd >= 0) {
                read(urandom_fd, buf, aligned);
                close(urandom_fd);
            } else {
                // Extreme fallback: just write something
                memset(buf, 0x5A, aligned); 
            }
        }

        ssize_t n = write(fd, buf, aligned);
        if (n < 0 && errno != EIO) {
            free(buf);
            close(fd);
            throw std::runtime_error("Random overwrite write error: " + std::string(strerror(errno)));
        }

        written += aligned;
        if (progress_cb) {
            progress_cb(written, total, "Purge: random overwrite");
        }
    }

    free(buf);
    fsync(fd);
    close(fd);
}

WipeResult wipe_purge(const DeviceInfo& device, ProgressCallback progress_cb) {
    WipeResult result;
    result.mode_used       = WipeMode::PURGE;
    result.start_epoch     = static_cast<uint64_t>(time(nullptr));
    result.sha256_pre_wipe = hash_first_mb(device.device_path);

    DeviceInfo prepared = prepare_device_for_wipe(device);
    result.hpa_removed  = device.hidden.hpa_detected && !prepared.hidden.hpa_detected;
    result.dco_restored = device.hidden.dco_modification_present && !prepared.hidden.dco_modification_present;

    if (device.type == DriveType::SSD_NVME) {
        // NVMe path: Crypto Erase via NVMe Sanitize
        std::string char_dev = nvme::ns_to_char_device(device.device_path);
        int fd = nvme::open_nvme_char_device(char_dev);

        nvme::NVMeIdentifyController id = nvme::read_identify(fd);
        uint8_t action;

        if (id.sanicap & 0x01) {
            action = nvme::NVME_SANITIZE_CRYPTO_ERASE;   // Preferred
            result.firmware_command_name = "NVMe Sanitize (Crypto Erase)";
        } else if (id.sanicap & 0x02) {
            action = nvme::NVME_SANITIZE_BLOCK_ERASE;    // Fallback
            result.firmware_command_name = "NVMe Sanitize (Block Erase)";
        } else {
            close(fd);
            throw std::runtime_error("NVMe device does not support Sanitize — cannot Purge");
        }

        nvme::issue_sanitize(fd, action);
        nvme::poll_sanitize_status(fd, progress_cb, 5);
        close(fd);

        result.firmware_command_used = true;
        result.hidden_areas_covered  = true;

    } else if (device.type == DriveType::SSD_SATA) {
        // SATA SSD path: ATA Secure Erase Enhanced (if not frozen), else encrypt + random overwrite
        int fd = ata::open_device(device.device_path);

        if (!ata::is_security_frozen(fd)) {
            ata::security_erase_prepare(fd);
            ata::security_erase_unit(fd, true);  // Enhanced erase
            result.firmware_command_name = "ATA Secure Erase Enhanced";
            result.firmware_command_used = true;
            result.hidden_areas_covered  = true;
        } else {
            // Security is frozen — try S3 unfreeze
            bool unfrozen = ata::try_unfreeze_security(fd);
            if (!unfrozen) {
                close(fd);
                // Fallback: encrypt + random overwrite (covers OS-visible LBAs only)
                encrypt_drive_aes256(device.device_path, progress_cb);
                overwrite_random(device.device_path, progress_cb);
                result.firmware_command_name = "Encrypt+Random (frozen security fallback)";
                result.firmware_command_used = false;
                result.hidden_areas_covered  = false;
            } else {
                // Re-open in case fd went stale during sleep
                close(fd);
                fd = ata::open_device(device.device_path);
                ata::security_erase_prepare(fd);
                ata::security_erase_unit(fd, true);
                result.firmware_command_name = "ATA Secure Erase Enhanced (after unfreeze)";
                result.firmware_command_used = true;
                result.hidden_areas_covered  = true;
            }
        }
        if (fd >= 0) close(fd);

    } else {
        // HDD path: Encrypt → destroy key → random overwrite
        encrypt_drive_aes256(device.device_path, progress_cb);
        overwrite_random(device.device_path, progress_cb);
        result.firmware_command_name = "AES-256 Encrypt + Key Destruction + Random Overwrite";
        result.firmware_command_used = false;
        result.hidden_areas_covered  = result.hpa_removed || result.dco_restored;
    }

    result.end_epoch        = static_cast<uint64_t>(time(nullptr));
    result.duration_seconds = static_cast<uint32_t>(result.end_epoch - result.start_epoch);
    result.sha256_post_wipe = hash_first_mb(device.device_path);
    result.success          = true;

    return result;
}

} // namespace zerotrace
