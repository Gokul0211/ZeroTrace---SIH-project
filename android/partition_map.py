from dataclasses import dataclass
from typing import List, Optional
import re


@dataclass
class AndroidPartition:
    name: str               # e.g. "userdata", "cache", "metadata"
    block_device: str       # e.g. "/dev/block/sda32"
    size_bytes: int
    is_wipe_target: bool    # Whether ZeroTrace should wipe this partition


# Partitions that contain user data — these are wipe targets
WIPE_TARGET_PARTITIONS = {
    "userdata",     # Main user storage — apps, files, credentials
    "cache",        # App cache — may contain sensitive data
    "metadata",     # CRITICAL: stores wrapped FBE key blobs
    "misc",         # Miscellaneous settings — some sensitive data
}

# Partitions that must NEVER be wiped — bricking risk
PROTECTED_PARTITIONS = {
    "boot",
    "recovery",
    "system",
    "vendor",
    "persist",
    "modem",
    "abl",
    "xbl",
    "hyp",
    "tz",           # TrustZone firmware — never wipe
    "keystore",     # Not the same as /data/misc/keystore — this is hardware keystore
    "sbl1",
    "aboot",
    "rpm",
}


def map_partitions(device) -> List[AndroidPartition]:
    """
    Map all partitions via /dev/block/by-name symlinks.
    device: AndroidDevice instance

    Returns list of AndroidPartition objects.
    This requires root to get full partition info.
    Falls back to known partition names if non-root.
    """
    partitions = []

    # Try reading by-name symlinks (requires that /dev/block/by-name exists)
    ls_output = device.shell("ls -la /dev/block/by-name/ 2>/dev/null")

    if ls_output and "No such file" not in ls_output:
        # Parse: lrwxrwxrwx 1 root root 21 2023-01-01 00:00 userdata -> /dev/block/sda32
        pattern = re.compile(r'(\S+)\s+->\s+(\S+)$', re.MULTILINE)
        for match in pattern.finditer(ls_output):
            name = match.group(1)
            target = match.group(2)

            # Make sure target is absolute path
            if not target.startswith('/'):
                target = '/dev/block/' + target

            # Get partition size
            size = 0
            if device.check_root():
                size_str = device.shell_root(f"blockdev --getsize64 {target} 2>/dev/null")
                try:
                    size = int(size_str)
                except ValueError:
                    pass

            is_target = name in WIPE_TARGET_PARTITIONS
            partitions.append(AndroidPartition(
                name=name,
                block_device=target,
                size_bytes=size,
                is_wipe_target=is_target
            ))

    else:
        # Fallback: we know the common partition names, assume standard layout
        common_targets = ["userdata", "cache", "metadata"]
        for name in common_targets:
            # Try to find the block device
            result = device.shell(f"readlink -f /dev/block/by-name/{name} 2>/dev/null")
            if result and "No such" not in result:
                partitions.append(AndroidPartition(
                    name=name,
                    block_device=result,
                    size_bytes=0,
                    is_wipe_target=True
                ))

    return partitions


def get_userdata_block(device) -> Optional[str]:
    """Get the block device path for the userdata partition."""
    result = device.shell("readlink -f /dev/block/by-name/userdata 2>/dev/null")
    if result and "No such" not in result and result != "":
        return result
    return None


def get_metadata_block(device) -> Optional[str]:
    """Get the block device path for the metadata partition."""
    result = device.shell("readlink -f /dev/block/by-name/metadata 2>/dev/null")
    if result and "No such" not in result and result != "":
        return result
    return None


def get_base_storage_device(userdata_block: str) -> Optional[str]:
    """
    Given userdata block device (e.g. /dev/block/sda32),
    return the base storage device (e.g. /dev/block/sda).

    This is used for eMMC/UFS whole-device secure erase.
    """
    # Strip partition number from end
    match = re.match(r'(/dev/block/[a-zA-Z]+)', userdata_block)
    if match:
        return match.group(1)

    # Handle mmcblk style: /dev/block/mmcblk0p32 → /dev/block/mmcblk0
    match = re.match(r'(/dev/block/mmcblk\d+)p\d+', userdata_block)
    if match:
        return match.group(1)

    return None
