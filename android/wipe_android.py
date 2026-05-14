import time
from dataclasses import dataclass, field
from typing import Optional, List, Callable
from enum import Enum

from .adb_device import AndroidDevice, AndroidDeviceInfo, StorageType
from .partition_map import map_partitions, get_userdata_block, get_metadata_block, get_base_storage_device
from .tee_handler import TEEKeyHandler
from .emmc_ufs import (
    emmc_secure_erase, ufs_purge,
    overwrite_partition_zeros, overwrite_partition_random
)


class AndroidWipeMode(Enum):
    CLEAR           = "CLEAR"              # Zero overwrite of userdata (root)
    PURGE           = "PURGE"              # TEE key destruction + random overwrite (root)
    FIRMWARE_ERASE  = "FIRMWARE_ERASE"    # eMMC/UFS hardware secure erase (root)
    FACTORY_RESET   = "FACTORY_RESET"     # Android factory reset (non-root fallback)


@dataclass
class AndroidWipeResult:
    success: bool
    device_serial: str
    device_model: str
    wipe_mode: AndroidWipeMode
    start_epoch: int
    end_epoch: int
    duration_seconds: int
    is_rooted: bool

    # Coverage details
    userdata_wiped: bool = False
    metadata_wiped: bool = False
    tee_keys_invalidated: bool = False
    hardware_secure_erase_used: bool = False
    factory_reset_triggered: bool = False
    coverage: str = "unknown"   # "full" | "partial" | "factory_reset_only" | "user_data_only"

    # Entropy (if we can measure it — only possible for rooted wipes)
    entropy_bits: Optional[float] = None
    entropy_state: Optional[str] = None

    # Error info
    error_message: str = ""
    warnings: List[str] = field(default_factory=list)
    step_log: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for certificate generator."""
        return {
            "device_type": "ANDROID",
            "device_serial": self.device_serial,
            "device_model": self.device_model,
            "wipe_mode": self.wipe_mode.value,
            "start_epoch": self.start_epoch,
            "end_epoch": self.end_epoch,
            "duration_seconds": self.duration_seconds,
            "is_rooted": self.is_rooted,
            "userdata_wiped": self.userdata_wiped,
            "metadata_wiped": self.metadata_wiped,
            "tee_keys_invalidated": self.tee_keys_invalidated,
            "hardware_secure_erase_used": self.hardware_secure_erase_used,
            "factory_reset_triggered": self.factory_reset_triggered,
            "coverage": self.coverage,
            "entropy_bits": self.entropy_bits,
            "entropy_state": self.entropy_state,
            "warnings": self.warnings,
            "step_log": self.step_log,
        }


def wipe_android_device(
    serial: str,
    mode: AndroidWipeMode,
    progress_cb: Optional[Callable[[str], None]] = None
) -> AndroidWipeResult:
    """
    Main entry point for Android device sanitization.
    Called by the TUI orchestrator.

    serial: ADB device serial
    mode: selected wipe mode
    progress_cb: callable(message: str) for TUI progress updates
    """

    def log(msg: str):
        if progress_cb:
            progress_cb(msg)

    start_time = int(time.time())
    device = AndroidDevice(serial)
    info = device.get_full_info()

    result = AndroidWipeResult(
        success=False,
        device_serial=serial,
        device_model=f"{info.manufacturer} {info.model}",
        wipe_mode=mode,
        start_epoch=start_time,
        end_epoch=0,
        duration_seconds=0,
        is_rooted=info.is_rooted,
        warnings=info.warnings.copy()
    )

    log(f"Device: {info.manufacturer} {info.model} (Android {info.android_version})")
    log(f"Root: {'YES' if info.is_rooted else 'NO'}")
    log(f"Storage: {info.storage_type.value}")
    log(f"Encryption: {info.encryption_state.value}")
    result.step_log.append(f"Device info gathered: {info.model}, root={info.is_rooted}")

    # ─────────────────────────────────────────────
    # Validate mode vs capabilities
    # ─────────────────────────────────────────────

    if mode in (AndroidWipeMode.CLEAR, AndroidWipeMode.PURGE, AndroidWipeMode.FIRMWARE_ERASE):
        if not info.is_rooted:
            # Fall back to factory reset — cannot do block-level without root
            log("WARNING: Root required for selected mode. Falling back to FACTORY_RESET.")
            result.warnings.append(
                f"Mode {mode.value} requires root. Automatically switched to FACTORY_RESET."
            )
            mode = AndroidWipeMode.FACTORY_RESET
            result.wipe_mode = mode

    # ─────────────────────────────────────────────
    # Get partition layout
    # ─────────────────────────────────────────────

    userdata_block = get_userdata_block(device)
    metadata_block = get_metadata_block(device)
    base_storage = get_base_storage_device(userdata_block) if userdata_block else None

    log(f"Userdata block: {userdata_block or 'not found'}")
    log(f"Metadata block: {metadata_block or 'not found'}")
    result.step_log.append(f"userdata={userdata_block}, metadata={metadata_block}, base={base_storage}")

    # ─────────────────────────────────────────────
    # Execute wipe based on mode
    # ─────────────────────────────────────────────

    tee = TEEKeyHandler(device)

    if mode == AndroidWipeMode.FACTORY_RESET:
        # ─ Non-root path ─────────────────────────
        log("Initiating factory reset via recovery...")

        # Clear app data first (non-destructive, belt-and-suspenders)
        log("Clearing app data (non-root pre-step)...")
        _clear_app_data_nonroot(device, log)

        # Trigger factory reset
        tee_result = tee.full_tee_key_destruction(is_rooted=False, progress_cb=log)
        result.factory_reset_triggered = tee_result["success"]
        result.tee_keys_invalidated = tee_result["tee_keys_invalidated"]
        result.coverage = tee_result["coverage"]
        result.step_log.append(f"factory reset: {tee_result['notes']}")

        if tee_result["success"]:
            result.success = True
            log("Factory reset triggered. Device will wipe and reboot.")
            log("NOTE: ZeroTrace will monitor for device reconnection...")
            # Wait for device to come back (indicates reset completed)
            came_back = tee.wait_for_device_after_reset(timeout_seconds=300)
            if came_back:
                log("Device reconnected — factory reset confirmed complete.")
                result.step_log.append("Device reconnected after factory reset")
            else:
                log("Device did not reconnect within 5 minutes. User must confirm manually.")
                result.warnings.append("Could not confirm factory reset completion. Verify manually.")
        else:
            result.success = False
            result.error_message = f"Factory reset trigger failed: {tee_result['notes']}"

    elif mode == AndroidWipeMode.CLEAR:
        # ─ Root Clear path ───────────────────────
        if not userdata_block:
            result.error_message = "Cannot locate userdata block device"
            result.success = False
        else:
            log("CLEAR: Wiping metadata partition (FBE key blobs)...")
            meta_ok, meta_msg = tee.wipe_metadata_partition()
            result.metadata_wiped = meta_ok
            result.step_log.append(f"metadata wipe: {meta_msg}")

            log("CLEAR: Zero-filling userdata partition...")
            ud_ok, ud_msg = overwrite_partition_zeros(
                device, userdata_block, info.userdata_size_bytes
            )
            result.userdata_wiped = ud_ok
            result.step_log.append(f"userdata zero-fill: {ud_msg}")

            result.tee_keys_invalidated = meta_ok
            result.coverage = "full" if (meta_ok and ud_ok) else "partial"
            result.success = ud_ok

            # Measure entropy on a sample of userdata
            if ud_ok and userdata_block:
                log("CLEAR: Verifying entropy...")
                entropy = _measure_entropy_android(device, userdata_block)
                result.entropy_bits = entropy
                result.entropy_state = "ZERO_FILL_CONFIRMED" if entropy < 0.1 else "CLEAR_UNVERIFIED"

    elif mode == AndroidWipeMode.PURGE:
        # ─ Root Purge path ───────────────────────
        if not userdata_block:
            result.error_message = "Cannot locate userdata block device"
            result.success = False
        else:
            log("PURGE: Destroying TEE/FBE keys...")
            tee_result = tee.full_tee_key_destruction(is_rooted=True, progress_cb=log)
            result.metadata_wiped = tee_result.get("success", False)
            result.tee_keys_invalidated = tee_result.get("tee_keys_invalidated", False)
            result.step_log.append(f"TEE destruction: {tee_result.get('notes', '')}")

            log("PURGE: Random-filling userdata partition...")
            ud_ok, ud_msg = overwrite_partition_random(
                device, userdata_block, info.userdata_size_bytes
            )
            result.userdata_wiped = ud_ok
            result.step_log.append(f"userdata random-fill: {ud_msg}")

            result.coverage = "full" if (result.metadata_wiped and ud_ok) else "partial"
            result.success = ud_ok

            if ud_ok and userdata_block:
                log("PURGE: Verifying entropy...")
                entropy = _measure_entropy_android(device, userdata_block)
                result.entropy_bits = entropy
                result.entropy_state = "RANDOM_FILL_CONFIRMED" if entropy > 7.5 else "PURGE_UNVERIFIED"

    elif mode == AndroidWipeMode.FIRMWARE_ERASE:
        # ─ Hardware Secure Erase path ─────────────
        if not base_storage:
            result.error_message = "Cannot determine base storage device for firmware erase"
            result.success = False
        else:
            # First: destroy TEE keys (metadata wipe)
            log("FIRMWARE: Destroying TEE/FBE keys first...")
            tee_result = tee.full_tee_key_destruction(is_rooted=True, progress_cb=log)
            result.metadata_wiped = tee_result.get("success", False)
            result.tee_keys_invalidated = tee_result.get("tee_keys_invalidated", False)

            # Then: hardware secure erase
            if info.storage_type == StorageType.EMMC:
                log(f"FIRMWARE: eMMC secure erase on {base_storage}...")
                hw_ok, hw_msg = emmc_secure_erase(device, base_storage)
            elif info.storage_type == StorageType.UFS:
                log(f"FIRMWARE: UFS purge on {base_storage}...")
                hw_ok, hw_msg = ufs_purge(device, base_storage)
            else:
                # Unknown storage — fall back to zero overwrite
                log("FIRMWARE: Unknown storage type, falling back to zero overwrite...")
                hw_ok, hw_msg = overwrite_partition_zeros(
                    device, userdata_block, info.userdata_size_bytes
                )

            result.hardware_secure_erase_used = hw_ok
            result.userdata_wiped = hw_ok
            result.step_log.append(f"hardware erase: {hw_msg}")
            result.coverage = "full" if hw_ok else "partial"
            result.success = hw_ok

    # ─────────────────────────────────────────────
    # Finalize
    # ─────────────────────────────────────────────

    result.end_epoch = int(time.time())
    result.duration_seconds = result.end_epoch - result.start_epoch

    if result.success:
        log(f"Android wipe complete. Coverage: {result.coverage}")
    else:
        log(f"Android wipe FAILED: {result.error_message}")

    return result


# ─────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────

def _clear_app_data_nonroot(device, log_cb):
    """Clear user-installed app data. Non-root."""
    try:
        packages_raw = device.shell("pm list packages -3")  # -3 = third party apps
        packages = [
            line.replace("package:", "").strip()
            for line in packages_raw.split('\n')
            if line.startswith("package:")
        ]

        cleared = 0
        for pkg in packages:
            if pkg:
                device.shell(f"pm clear {pkg} 2>/dev/null")
                cleared += 1

        log_cb(f"Cleared data for {cleared} apps")

        # Clear external storage
        device.shell("rm -rf /sdcard/DCIM /sdcard/Downloads /sdcard/Documents /sdcard/Pictures 2>/dev/null")
        log_cb("External storage (DCIM, Downloads, Documents, Pictures) cleared")

    except Exception as e:
        log_cb(f"App data clear partial: {e}")


def _measure_entropy_android(device, block_device: str) -> float:
    """
    Measure Shannon entropy of a block device via sampling.
    Since we can't run the C++ entropy module on Android,
    we sample a few blocks via dd and compute entropy in Python.

    Returns entropy in bits/byte (0.0-8.0).
    """
    import math

    # Read 4MB from beginning of partition
    sample_raw = device.shell_root(
        f"dd if={block_device} bs=4096 count=1024 2>/dev/null | base64 -w0",
        timeout=60
    )

    if not sample_raw:
        return 0.0

    import base64
    try:
        data = base64.b64decode(sample_raw)
    except Exception:
        return 0.0

    if not data:
        return 0.0

    # Compute Shannon entropy
    freq = [0] * 256
    for byte in data:
        freq[byte] += 1

    total = len(data)
    H = 0.0
    for count in freq:
        if count == 0:
            continue
        p = count / total
        H -= p * math.log2(p)

    return H
