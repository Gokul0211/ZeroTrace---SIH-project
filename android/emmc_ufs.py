from typing import Tuple


def emmc_secure_erase(device, base_storage_device: str) -> Tuple[bool, str]:
    """
    Issue eMMC Secure Erase command via mmc-utils.
    This tells the eMMC controller to erase ALL physical NAND cells
    including wear-leveled blocks inaccessible via normal LBA writes.

    base_storage_device: the base mmcblk device, e.g. /dev/block/mmcblk0

    WARNING: This operates on the entire storage chip, not just one partition.
    All data is permanently erased.
    """
    if not device.check_root():
        return False, "Root required for eMMC secure erase"

    # Check if mmc-utils is available
    mmc_check = device.shell("which mmc 2>/dev/null")
    if not mmc_check:
        return False, "mmc-utils not available on device"

    # mmc erase secure <device>
    # This sends CMD38 with argument 0x80000000 (SECURE_ERASE)
    cmd = f"mmc erase secure {base_storage_device}"
    result = device.shell_root(cmd, timeout=300)  # Can take minutes

    if "error" in result.lower() or "failed" in result.lower():
        # Fallback: try TRIM-based erase
        cmd2 = f"mmc erase {base_storage_device}"
        result2 = device.shell_root(cmd2, timeout=300)
        if "error" in result2.lower():
            return False, f"eMMC secure erase failed: {result}. Trim also failed: {result2}"
        return True, f"eMMC TRIM erase completed (secure erase unavailable): {result2}"

    return True, f"eMMC secure erase completed: {result}"


def emmc_sanitize(device, base_storage_device: str) -> Tuple[bool, str]:
    """
    Issue eMMC Sanitize command (CMD6 with SANITIZE_START argument).
    More thorough than secure erase on some eMMC chips.
    Available on eMMC 5.0+ devices.
    """
    if not device.check_root():
        return False, "Root required"

    # Check eMMC version
    mmc_info = device.shell(f"cat /sys/block/mmcblk0/device/csd 2>/dev/null")

    # Issue sanitize via mmc-utils
    cmd = f"mmc sanitize {base_storage_device}"
    result = device.shell_root(cmd, timeout=600)

    if "error" in result.lower():
        return False, f"eMMC sanitize failed: {result}"
    return True, f"eMMC sanitize completed: {result}"


def ufs_purge(device, base_storage_device: str) -> Tuple[bool, str]:
    """
    Issue UFS PURGE command via ufs-utils.
    UFS Purge sanitizes all blocks including wear-leveling pool.
    Available on UFS 2.0+ devices.
    """
    if not device.check_root():
        return False, "Root required for UFS purge"

    # Check if ufs-utils is available
    ufs_check = device.shell("which ufs-utils 2>/dev/null")
    if not ufs_check:
        # Try the vendor-provided path
        ufs_check = device.shell("ls /vendor/bin/ufs-utils 2>/dev/null")
        if not ufs_check:
            return False, "ufs-utils not available on device"
        ufs_cmd = "/vendor/bin/ufs-utils"
    else:
        ufs_cmd = "ufs-utils"

    # UFS Purge command
    cmd = f"{ufs_cmd} --purge {base_storage_device}"
    result = device.shell_root(cmd, timeout=600)

    if "error" in result.lower() or "failed" in result.lower():
        return False, f"UFS purge failed: {result}"
    return True, f"UFS purge completed: {result}"


def overwrite_partition_zeros(device, partition_block: str, size_bytes: int) -> Tuple[bool, str]:
    """
    Overwrite a partition with zeros via dd.
    Used as fallback when hardware secure erase is unavailable.
    Also used as the primary Clear mode for Android.

    partition_block: absolute block device path e.g. /dev/block/sda32
    size_bytes: size of partition (used to calculate count)
    """
    if not device.check_root():
        return False, "Root required for block-level overwrite"

    size_mb = max(1, size_bytes // (1024 * 1024))

    cmd = (
        f"dd if=/dev/zero of={partition_block} bs=1M count={size_mb} conv=fsync 2>&1"
    )
    result = device.shell_root(cmd, timeout=3600)  # Up to 1 hour for large partitions

    if "error" in result.lower() and "records out" not in result.lower():
        return False, f"dd overwrite failed: {result}"
    return True, f"Partition zero-filled: {result}"


def overwrite_partition_random(device, partition_block: str, size_bytes: int) -> Tuple[bool, str]:
    """
    Overwrite a partition with random data via dd.
    Used as Purge mode for Android partitions.
    """
    if not device.check_root():
        return False, "Root required"

    size_mb = max(1, size_bytes // (1024 * 1024))

    cmd = (
        f"dd if=/dev/urandom of={partition_block} bs=1M count={size_mb} conv=fsync 2>&1"
    )
    result = device.shell_root(cmd, timeout=7200)

    if "error" in result.lower() and "records out" not in result.lower():
        return False, f"Random overwrite failed: {result}"
    return True, f"Partition random-filled: {result}"
