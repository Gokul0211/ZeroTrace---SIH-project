#include "device.hpp"
#include "ata.hpp"
#include "nvme.hpp"
#include <filesystem>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <vector>
#include <sys/ioctl.h>
#include <linux/fs.h>
#include <fcntl.h>
#include <unistd.h>
#include <cerrno>
#include <cstring>

namespace zerotrace {

// ─────────────────────────────────────────────
// Block Device Enumeration
// ─────────────────────────────────────────────

std::vector<std::string> enumerate_block_devices() {
    std::vector<std::string> devices;
    const std::string sys_block = "/sys/block";

    if (!std::filesystem::exists(sys_block)) {
        throw std::runtime_error("/sys/block not found — is this Linux?");
    }

    for (const auto& entry : std::filesystem::directory_iterator(sys_block)) {
        std::string name = entry.path().filename().string();

        // Skip loop devices, ram devices, device mapper, md raid
        if (name.rfind("loop", 0) == 0) continue;
        if (name.rfind("ram",  0) == 0) continue;
        if (name.rfind("dm-",  0) == 0) continue;
        if (name.rfind("md",   0) == 0) continue;
        if (name.rfind("zram", 0) == 0) continue;

        // Skip removable devices (USB sticks — likely the boot USB)
        std::string removable_path = sys_block + "/" + name + "/removable";
        std::ifstream removable_file(removable_path);
        if (removable_file.is_open()) {
            std::string val;
            std::getline(removable_file, val);
            if (val == "1") continue;  // Skip removable
        }

        devices.push_back("/dev/" + name);
    }
    return devices;
}

// ─────────────────────────────────────────────
// Drive Type Detection
// ─────────────────────────────────────────────

DriveType detect_drive_type(const std::string& device_path) {
    // Strip "/dev/" prefix
    std::string name = device_path;
    if (name.rfind("/dev/", 0) == 0) {
        name = name.substr(5);
    }

    // NVMe: nvme0n1, nvme1n1, etc.
    if (name.rfind("nvme", 0) == 0) {
        return DriveType::SSD_NVME;
    }

    // Check rotational flag in sysfs — 0 = SSD, 1 = HDD
    std::string rot_path = "/sys/block/" + name + "/queue/rotational";
    std::ifstream rot_file(rot_path);
    if (rot_file.is_open()) {
        std::string val;
        std::getline(rot_file, val);
        if (val == "0") return DriveType::SSD_SATA;
        if (val == "1") return DriveType::HDD;
    }

    // Check USB transport via sysfs device symlink
    std::string dev_path = "/sys/block/" + name + "/device";
    if (std::filesystem::exists(dev_path)) {
        std::error_code ec;
        std::string real = std::filesystem::canonical(dev_path, ec).string();
        if (!ec && real.find("usb") != std::string::npos) {
            return DriveType::USB_DRIVE;
        }
    }

    return DriveType::UNKNOWN;
}

// ─────────────────────────────────────────────
// ioctl Helpers
// ─────────────────────────────────────────────

uint64_t get_device_size(int fd) {
    uint64_t size = 0;
    if (ioctl(fd, BLKGETSIZE64, &size) < 0) {
        throw std::runtime_error(
            std::string("ioctl BLKGETSIZE64 failed: ") + strerror(errno));
    }
    return size;
}

uint32_t get_sector_size(int fd) {
    uint32_t size = 512;
    ioctl(fd, BLKSSZGET, &size);  // Non-fatal; 512 is safe default
    return size;
}

} // namespace zerotrace
