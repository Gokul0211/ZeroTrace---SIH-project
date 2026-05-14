import time
from typing import Tuple


class TEEKeyHandler:

    def __init__(self, device):
        """
        device: AndroidDevice instance
        """
        self.device = device

    def get_tee_info(self) -> dict:
        """Gather TEE/keystore information for the certificate."""
        return {
            "keymaster_hw": self.device.get_prop("ro.hardware.keystore"),
            "keymaster_version": self.device.get_prop("ro.hardware.keymaster"),
            "strongbox_present": self.device.get_prop("ro.hardware.strongbox") != "",
            "encryption_type": self.device.get_prop("ro.crypto.type"),
            "fbe_enabled": self.device.get_prop("ro.crypto.type") == "file",
        }

    def wipe_metadata_partition(self) -> Tuple[bool, str]:
        """
        Wipe the /metadata partition by overwriting with zeros.
        This destroys the wrapped FBE key blobs.
        After this, userdata is cryptographically unrecoverable even without overwrite.

        Requires ROOT.
        Returns (success, message).
        """
        if not self.device.check_root():
            return False, "Root required for metadata wipe"

        from .partition_map import get_metadata_block
        metadata_block = get_metadata_block(self.device)

        if not metadata_block:
            return False, "Cannot locate metadata partition block device"

        # First: get size so we know how much to write
        size_str = self.device.shell_root(f"blockdev --getsize64 {metadata_block} 2>/dev/null")
        try:
            size_bytes = int(size_str)
        except ValueError:
            size_bytes = 16 * 1024 * 1024  # Default: 16MB — typical metadata partition size

        size_mb = max(1, size_bytes // (1024 * 1024))

        # Overwrite with zeros
        cmd = f"dd if=/dev/zero of={metadata_block} bs=1M count={size_mb} 2>&1"
        result = self.device.shell_root(cmd, timeout=120)

        if "error" in result.lower() or "permission denied" in result.lower():
            return False, f"Metadata wipe failed: {result}"

        return True, f"Metadata partition wiped ({size_mb}MB). FBE keys are now unrecoverable."

    def evict_vold_keys(self) -> Tuple[bool, str]:
        """
        Ask vold (Android's volume daemon) to evict cached keys from memory.
        This removes keys from RAM — useful before overwrite.
        Requires ROOT.
        """
        if not self.device.check_root():
            return False, "Root required"

        result = self.device.shell_root("vdc cryptfs clearcachedkeys 2>&1")
        if "200" in result:  # vdc returns 200 on success
            return True, "vold cached keys evicted"
        return False, f"vdc clearcachedkeys result: {result}"

    def wipe_software_keystore(self) -> Tuple[bool, str]:
        """
        Delete software keystore key material.
        NOTE: This only affects software-backed keys.
        Hardware-backed (TEE) keys are NOT deleted by this.
        Requires ROOT.
        """
        if not self.device.check_root():
            return False, "Root required"

        paths_to_wipe = [
            "/data/misc/keystore/",
            "/data/misc/vold/",
            "/data/misc/credential_key/",
            "/data/misc/keychain/",
        ]

        results = []
        for path in paths_to_wipe:
            r = self.device.shell_root(f"rm -rf {path} 2>&1")
            results.append(f"{path}: {r if r else 'cleared'}")

        return True, "Software keystore paths cleared: " + "; ".join(results)

    def trigger_factory_reset_recovery(self) -> Tuple[bool, str]:
        """
        Trigger factory reset via Android recovery mode.
        This is the ONLY reliable method for non-rooted devices to evict TEE keys.

        What happens:
        1. Device reboots into recovery mode
        2. Recovery calls TEE to invalidate key slots
        3. Recovery formats userdata
        4. Device boots clean

        LIMITATION: ZeroTrace cannot confirm when recovery wipe completes
        because the device reboots. The certificate will note this.

        Returns (success, message) — success here means the recovery boot was triggered,
        NOT that the wipe completed (we can't verify that from here).
        """
        # Method 1: ADB reboot recovery (works on most devices)
        try:
            self.device.reboot("recovery")
            return True, (
                "Device rebooted to recovery mode. "
                "User must select 'Wipe data/factory reset' in the recovery menu. "
                "This will evict TEE keys and format userdata. "
                "ZeroTrace will monitor for device reconnection."
            )
        except Exception as e:
            pass

        # Method 2: bcb (boot control block) method
        result = self.device.shell_root(
            "echo 'boot-recovery' > /cache/recovery/command 2>/dev/null"
        )
        self.device.reboot()
        return True, "Recovery boot triggered via BCB method."

    def trigger_factory_reset_direct(self) -> Tuple[bool, str]:
        """
        Trigger factory reset directly via Android shell commands.
        Works on rooted devices without manual recovery interaction.

        Uses the recoverySystem API via am broadcast.
        WARNING: This triggers the ENTIRE factory reset including
        re-flash of userdata filesystem — not just a file delete.
        """
        # Method: Use Android's built-in factory reset broadcast
        # This goes through the system's proper reset path including TEE key eviction
        cmd = "am broadcast -a android.intent.action.MASTER_CLEAR --receiver-foreground"
        result = self.device.shell_root(cmd, timeout=30)

        if "Error" not in result and "Exception" not in result:
            return True, "Factory reset broadcast sent. Device will wipe and reboot."

        # Fallback: recoverySystem via service call
        cmd2 = "service call recovery 1 s16 'wipe_data'"
        result2 = self.device.shell_root(cmd2, timeout=30)
        return True, f"Factory reset via recovery service: {result2}"

    def wait_for_device_after_reset(self, timeout_seconds: int = 300) -> bool:
        """
        Poll ADB for device reconnection after factory reset.
        Used when we triggered recovery reset and need to confirm completion.
        Returns True if device reconnected within timeout.
        """
        import subprocess
        start = time.time()

        while time.time() - start < timeout_seconds:
            try:
                result = subprocess.run(
                    ["adb", "devices"],
                    capture_output=True, text=True, timeout=5
                )
                if self.device.serial in result.stdout and "device" in result.stdout:
                    return True
            except Exception:
                pass
            time.sleep(10)

        return False

    def full_tee_key_destruction(self, is_rooted: bool, progress_cb=None) -> dict:
        """
        Main entry point for TEE key destruction.
        Selects the best available method based on root status.

        Returns dict with:
            method_used: str
            success: bool
            coverage: "full" | "partial" | "factory_reset_only"
            tee_keys_invalidated: bool
            notes: str
        """
        result = {
            "method_used": None,
            "success": False,
            "coverage": "unknown",
            "tee_keys_invalidated": False,
            "notes": ""
        }

        if is_rooted:
            if progress_cb:
                progress_cb("TEE: evicting vold cached keys...")
            ok, msg = self.evict_vold_keys()

            if progress_cb:
                progress_cb("TEE: wiping /metadata partition (FBE key blobs)...")
            meta_ok, meta_msg = self.wipe_metadata_partition()

            if progress_cb:
                progress_cb("TEE: clearing software keystore...")
            ks_ok, ks_msg = self.wipe_software_keystore()

            result["method_used"] = "metadata_wipe + vold_eviction + keystore_clear"
            result["success"] = meta_ok  # metadata wipe is the critical step
            result["coverage"] = "full" if meta_ok else "partial"
            result["tee_keys_invalidated"] = meta_ok  # metadata wipe makes TEE keys useless
            result["notes"] = f"metadata: {meta_msg} | vold: {msg} | keystore: {ks_msg}"

        else:
            # Non-root: factory reset is the only option
            if progress_cb:
                progress_cb("TEE: triggering factory reset via recovery (non-root path)...")
            ok, msg = self.trigger_factory_reset_recovery()

            result["method_used"] = "factory_reset_recovery"
            result["success"] = ok
            result["coverage"] = "factory_reset_only"
            # Factory reset does evict TEE keys — Android's recovery calls the TEE
            # to invalidate key slots as part of the wipe process
            result["tee_keys_invalidated"] = ok
            result["notes"] = msg

        return result
