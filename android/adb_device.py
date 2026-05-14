import subprocess
import re
import time
import json
from dataclasses import dataclass, field
from typing import Optional, List
from enum import Enum


class StorageType(Enum):
    EMMC    = "eMMC"
    UFS     = "UFS"
    UNKNOWN = "Unknown"


class AndroidEncryptionState(Enum):
    ENCRYPTED     = "encrypted"       # FBE or FDE active
    UNENCRYPTED   = "unencrypted"     # No encryption (very old device)
    ENCRYPTING    = "encrypting"      # In progress
    UNSUPPORTED   = "unsupported"     # Cannot determine
    UNKNOWN       = "unknown"


@dataclass
class AndroidDeviceInfo:
    serial: str
    model: str
    manufacturer: str
    android_version: str
    sdk_version: int
    build_id: str
    storage_type: StorageType
    is_rooted: bool
    encryption_state: AndroidEncryptionState
    tee_backed_keys: bool               # True if TEE/StrongBox backs encryption keys
    bootloader_unlocked: bool
    userdata_size_bytes: int
    available_wipe_methods: List[str]   # Populated after analysis
    warnings: List[str] = field(default_factory=list)


def detect_android_devices() -> List[str]:
    """
    Run `adb devices` and return list of connected device serials.
    Returns empty list if ADB is not available or no devices connected.
    """
    try:
        result = subprocess.run(
            ["adb", "devices"],
            capture_output=True,
            text=True,
            timeout=10
        )
    except FileNotFoundError:
        return []  # ADB not installed
    except subprocess.TimeoutExpired:
        return []

    serials = []
    lines = result.stdout.strip().split('\n')

    # First line is "List of devices attached" — skip it
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split('\t')
        if len(parts) == 2 and parts[1] == 'device':
            serials.append(parts[0])
        elif len(parts) == 2 and parts[1] == 'unauthorized':
            # Device connected but USB debugging not authorized
            # Return it with a special marker so TUI can show instructions
            serials.append(f"UNAUTHORIZED:{parts[0]}")
        elif len(parts) == 2 and parts[1] == 'offline':
            serials.append(f"OFFLINE:{parts[0]}")

    return serials


class AndroidDevice:
    """
    Represents a single connected Android device.
    All operations go through ADB shell.
    """

    def __init__(self, serial: str):
        self.serial = serial
        self._base_cmd = ["adb", "-s", serial]

    def shell(self, cmd: str, timeout: int = 30) -> str:
        """
        Execute a command on the device via ADB shell.
        Returns stdout as string. Raises on ADB failure.
        Does NOT raise on non-zero exit code from the shell command itself —
        check the return value.
        """
        try:
            result = subprocess.run(
                self._base_cmd + ["shell", cmd],
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            raise TimeoutError(f"ADB shell command timed out: {cmd}")

    def shell_root(self, cmd: str, timeout: int = 60) -> str:
        """
        Execute a command as root via `su -c`.
        Call check_root() first to confirm root is available.
        """
        return self.shell(f"su -c '{cmd}'", timeout=timeout)

    def push_file(self, local_path: str, remote_path: str) -> bool:
        """Push a file to the device. Returns True on success."""
        result = subprocess.run(
            self._base_cmd + ["push", local_path, remote_path],
            capture_output=True, text=True, timeout=60
        )
        return result.returncode == 0

    def reboot(self, mode: str = ""):
        """
        Reboot the device.
        mode: "" = normal reboot, "recovery" = reboot to recovery, "bootloader" = fastboot
        """
        cmd = self._base_cmd + ["reboot"]
        if mode:
            cmd.append(mode)
        subprocess.run(cmd, capture_output=True, timeout=10)

    # ─────────────────────────────────────────────
    # Device Property Helpers
    # ─────────────────────────────────────────────

    def get_prop(self, prop_name: str) -> str:
        return self.shell(f"getprop {prop_name}")

    def check_root(self) -> bool:
        """
        Check if the device has root access via su.
        Multiple methods tried in order.
        """
        # Method 1: Standard su check
        result = self.shell("su -c 'id' 2>/dev/null")
        if "uid=0" in result:
            return True

        # Method 2: Check if su binary exists
        result = self.shell("which su 2>/dev/null")
        if result and result != "":
            # su exists — test it
            result2 = self.shell("su 0 id 2>/dev/null")
            if "uid=0" in result2:
                return True

        # Method 3: Magisk-style su
        result = self.shell("/system/bin/su -c id 2>/dev/null")
        if "uid=0" in result:
            return True

        return False

    def check_encryption_state(self) -> AndroidEncryptionState:
        prop = self.get_prop("ro.crypto.state")
        if prop == "encrypted":
            return AndroidEncryptionState.ENCRYPTED
        elif prop == "unencrypted":
            return AndroidEncryptionState.UNENCRYPTED
        elif prop == "encrypting":
            return AndroidEncryptionState.ENCRYPTING
        return AndroidEncryptionState.UNKNOWN

    def check_tee_backed_keys(self) -> bool:
        """
        Determine if encryption keys are hardware-backed (TEE/StrongBox).
        On Android 7+ with FBE, keys are almost always TEE-backed.
        """
        # Check keymaster version
        keymaster = self.get_prop("ro.hardware.keystore")
        if keymaster and keymaster not in ["", "software"]:
            return True  # Hardware keymaster = TEE-backed

        # Check for StrongBox
        strongbox = self.get_prop("ro.hardware.strongbox")
        if strongbox and strongbox != "":
            return True

        # Check SDK version — FBE mandatory on Android 10+ = TEE-backed
        sdk = self.get_sdk_version()
        if sdk >= 29:  # Android 10
            return True

        # Check vold properties
        vold_encrypt = self.get_prop("ro.crypto.type")
        if vold_encrypt == "file":  # FBE
            return True

        return False

    def check_bootloader_unlocked(self) -> bool:
        prop = self.get_prop("ro.boot.verifiedbootstate")
        if prop in ["orange", "yellow"]:
            return True
        prop2 = self.get_prop("sys.oem_unlock_allowed")
        return prop2 == "1"

    def get_sdk_version(self) -> int:
        try:
            return int(self.get_prop("ro.build.version.sdk"))
        except (ValueError, TypeError):
            return 0

    def detect_storage_type(self) -> StorageType:
        """
        Detect whether device uses eMMC or UFS storage.
        Check /sys/bus platform drivers.
        """
        # UFS check — look for UFS host controller in sysfs
        ufs_check = self.shell("ls /sys/bus/platform/drivers/ufshcd/ 2>/dev/null | head -1")
        if ufs_check and "No such" not in ufs_check and ufs_check != "":
            return StorageType.UFS

        # eMMC check
        emmc_check = self.shell("ls /sys/bus/mmc/drivers/mmcblk/ 2>/dev/null | head -1")
        if emmc_check and "No such" not in emmc_check and emmc_check != "":
            return StorageType.EMMC

        # Alternative: check /proc/partitions for mmcblk devices
        proc_parts = self.shell("cat /proc/partitions 2>/dev/null")
        if "mmcblk" in proc_parts:
            return StorageType.EMMC

        return StorageType.UNKNOWN

    def get_userdata_size(self) -> int:
        """Get size of userdata partition in bytes."""
        # Try via df
        df_out = self.shell("df /data 2>/dev/null | tail -1")
        if df_out:
            parts = df_out.split()
            if len(parts) >= 2:
                try:
                    # df reports in 1K blocks by default
                    return int(parts[1]) * 1024
                except ValueError:
                    pass

        # Try via blockdev on the userdata block device
        userdata_block = self.shell(
            "readlink -f /dev/block/by-name/userdata 2>/dev/null"
        )
        if userdata_block:
            size_str = self.shell(f"blockdev --getsize64 {userdata_block} 2>/dev/null")
            try:
                return int(size_str)
            except ValueError:
                pass

        return 0

    # ─────────────────────────────────────────────
    # Full Device Scan
    # ─────────────────────────────────────────────

    def get_full_info(self) -> AndroidDeviceInfo:
        """
        Gather complete device information.
        This is called once at the start of the workflow.
        """
        warnings = []

        is_rooted = self.check_root()
        enc_state = self.check_encryption_state()
        tee_backed = self.check_tee_backed_keys()
        bootloader = self.check_bootloader_unlocked()
        storage_type = self.detect_storage_type()
        sdk = self.get_sdk_version()
        userdata_size = self.get_userdata_size()

        # Determine available wipe methods
        available_methods = []

        if is_rooted:
            available_methods.append("block_overwrite_root")
            available_methods.append("metadata_wipe_root")
            if storage_type == StorageType.EMMC:
                available_methods.append("emmc_secure_erase")
            elif storage_type == StorageType.UFS:
                available_methods.append("ufs_purge")

        # Factory reset is always available
        available_methods.append("factory_reset_recovery")
        available_methods.append("app_data_clear_nonroot")

        # Warnings
        if not is_rooted:
            warnings.append(
                "Device is NOT rooted. Wipe coverage is limited to user-accessible data only. "
                "Root access or bootloader unlock is required for full block-level sanitization."
            )

        if tee_backed and not is_rooted:
            warnings.append(
                "Device uses TEE-backed encryption keys. These cannot be deleted via ADB without root. "
                "Factory reset via recovery is required to trigger proper key eviction."
            )

        if not bootloader and not is_rooted:
            warnings.append(
                "Bootloader is locked and device is not rooted. "
                "Wipe is limited to factory reset level. This is still effective for most cases "
                "since TEE key eviction occurs during factory reset."
            )

        return AndroidDeviceInfo(
            serial=self.serial,
            model=self.get_prop("ro.product.model"),
            manufacturer=self.get_prop("ro.product.manufacturer"),
            android_version=self.get_prop("ro.build.version.release"),
            sdk_version=sdk,
            build_id=self.get_prop("ro.build.id"),
            storage_type=storage_type,
            is_rooted=is_rooted,
            encryption_state=enc_state,
            tee_backed_keys=tee_backed,
            bootloader_unlocked=bootloader,
            userdata_size_bytes=userdata_size,
            available_wipe_methods=available_methods,
            warnings=warnings
        )
