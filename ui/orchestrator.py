# ui/orchestrator.py
#
# The orchestrator handles all logic and state.
# The TUI screens only render data that the orchestrator provides,
# and pass user choices back to the orchestrator.
#
# Workflow:
#   1. scan_all_devices()           → populates device list
#   2. select_device(idx)           → picks target
#   3. select_wipe_mode(mode)       → picks mode
#   4. execute_wipe(progress_cb)    → runs wipe, returns WipeSession
#   5. run_entropy_check()          → runs entropy on result
#   6. finalize_session()           → packages everything for cert generator

import time
from dataclasses import dataclass, field
from typing import List, Optional, Union, Callable

# Phase 1: C++ core engine
try:
    import zerotrace_core as core
    CORE_AVAILABLE = True
except ImportError:
    CORE_AVAILABLE = False
    print("WARNING: zerotrace_core not available. Running in demo mode.")

# Phase 2: Android module
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from android.adb_device import detect_android_devices, AndroidDevice, AndroidDeviceInfo
from android.wipe_android import wipe_android_device, AndroidWipeMode, AndroidWipeResult


# ─────────────────────────────────────────────
# Data Structures
# ─────────────────────────────────────────────

@dataclass
class DisplayDevice:
    """
    A unified device representation for the UI.
    Wraps both PC drives (DeviceInfo) and Android devices (AndroidDeviceInfo).
    """
    idx: int                    # Index in the device list
    is_android: bool
    display_name: str           # "Samsung 860 EVO 500GB" or "Pixel 7 (Android 14)"
    display_type: str           # "SSD (NVMe)" or "Android (eMMC)"
    display_size: str           # "465.8 GB" or "128 GB"
    display_health: str         # "PASSED" or "Rooted" or "Non-root"
    warnings: List[str]

    # One of these will be set, not both
    pc_device: Optional[object] = None     # zerotrace_core.DeviceInfo
    android_device: Optional['AndroidDeviceInfo'] = None
    android_serial: Optional[str] = None


@dataclass
class WipeSession:
    """
    Complete record of a wipe operation.
    Passed to the certificate generator in Phase 4.
    """
    # Device
    device: DisplayDevice

    # Wipe
    wipe_mode_str: str          # "CLEAR" / "PURGE" / "FIRMWARE_DELETION"
    wipe_result: object         # core.WipeResult or AndroidWipeResult

    # Entropy
    entropy_result: Optional[object] = None  # core.EntropyResult or dict

    # Valuation
    valuation: Optional[dict] = None

    # Timing
    session_start: int = field(default_factory=lambda: int(time.time()))

    # Certificate output paths
    cert_pdf_path: Optional[str] = None
    cert_json_path: Optional[str] = None


# ─────────────────────────────────────────────
# Main Orchestrator Class
# ─────────────────────────────────────────────

class Orchestrator:

    def __init__(self):
        self.devices: List[DisplayDevice] = []
        self.selected_device: Optional[DisplayDevice] = None
        self.selected_mode: Optional[str] = None       # "CLEAR", "PURGE", "FIRMWARE_DELETION"
        self.current_session: Optional[WipeSession] = None
        self.scan_errors: List[str] = []

    def scan_all_devices(self) -> List[DisplayDevice]:
        """
        Scan for all PC drives and Android devices.
        Populates self.devices.
        Returns the device list for the UI to display.
        """
        self.devices = []
        self.scan_errors = []
        idx = 0

        # ── PC Drives ─────────────────────────────
        if CORE_AVAILABLE:
            try:
                block_devices = core.enumerate_block_devices()
            except Exception as e:
                self.scan_errors.append(f"Drive scan failed: {e}")
                block_devices = []

            for dev_path in block_devices:
                try:
                    # Determine if NVMe or ATA
                    if 'nvme' in dev_path:
                        dev_info = core.scan_nvme_device(dev_path)
                    else:
                        dev_info = core.scan_ata_device(dev_path)

                    display = self._make_display_device_pc(idx, dev_info)
                    self.devices.append(display)
                    idx += 1

                except Exception as e:
                    self.scan_errors.append(f"Cannot scan {dev_path}: {e}")

        # ── Android Devices ───────────────────────
        try:
            android_serials = detect_android_devices()
        except Exception as e:
            self.scan_errors.append(f"ADB scan failed: {e}")
            android_serials = []

        for serial in android_serials:
            if serial.startswith("UNAUTHORIZED:"):
                real_serial = serial.split(":")[1]
                # Create a placeholder device with a warning
                disp = DisplayDevice(
                    idx=idx,
                    is_android=True,
                    display_name=f"Android Device ({real_serial[:8]}...)",
                    display_type="Android — UNAUTHORIZED",
                    display_size="Unknown",
                    display_health="USB Debugging not authorized",
                    warnings=["Enable USB Debugging authorization on the device screen."],
                    android_serial=real_serial
                )
                self.devices.append(disp)
                idx += 1
                continue

            try:
                adb_dev = AndroidDevice(serial)
                info = adb_dev.get_full_info()
                display = self._make_display_device_android(idx, serial, info)
                self.devices.append(display)
                idx += 1
            except Exception as e:
                self.scan_errors.append(f"Cannot scan Android {serial}: {e}")

        return self.devices

    def _make_display_device_pc(self, idx: int, dev_info) -> DisplayDevice:
        """Convert C++ DeviceInfo to DisplayDevice."""
        from android.adb_device import AndroidDeviceInfo  # just for type check

        # Friendly type label
        type_map = {
            0: "HDD (SATA)",
            1: "SSD (SATA)",
            2: "SSD (NVMe)",
            3: "USB Drive",
            4: "Unknown",
        }
        type_str = type_map.get(int(dev_info.type), "Unknown")

        # Health string
        health_map = {0: "✓ PASSED", 1: "⚠ WARNING", 2: "✗ FAILED", 3: "? UNKNOWN"}
        health_str = health_map.get(int(dev_info.smart.overall_health), "UNKNOWN")

        # Warnings
        warnings = []
        if dev_info.hidden.hpa_detected:
            warnings.append(f"HPA detected: {dev_info.hidden.hpa_hidden_lbas} hidden sectors")
        if dev_info.hidden.dco_modification_present:
            warnings.append("DCO modification detected")
        if dev_info.hidden.security_frozen:
            warnings.append("ATA security frozen — may limit Firmware Deletion mode")
        if dev_info.is_ssd and dev_info.smart.wear_leveling_count > 0:
            warnings.append(f"SSD wear leveling count: {dev_info.smart.wear_leveling_count}")

        size_str = f"{dev_info.size_gb:.1f} GB"

        return DisplayDevice(
            idx=idx,
            is_android=False,
            display_name=f"{dev_info.model} ({size_str})" if dev_info.model else f"{dev_info.device_path} ({size_str})",
            display_type=type_str,
            display_size=size_str,
            display_health=health_str,
            warnings=warnings,
            pc_device=dev_info
        )

    def _make_display_device_android(self, idx: int, serial: str, info: AndroidDeviceInfo) -> DisplayDevice:
        """Convert AndroidDeviceInfo to DisplayDevice."""
        type_str = f"Android {info.android_version} ({info.storage_type.value})"
        size_str = f"{info.userdata_size_bytes // (1024*1024*1024):.0f} GB" if info.userdata_size_bytes > 0 else "Unknown"
        health_str = "Rooted" if info.is_rooted else "Non-root (limited)"

        return DisplayDevice(
            idx=idx,
            is_android=True,
            display_name=f"{info.manufacturer} {info.model}",
            display_type=type_str,
            display_size=size_str,
            display_health=health_str,
            warnings=info.warnings.copy(),
            android_device=info,
            android_serial=serial
        )

    def select_device(self, idx: int) -> bool:
        """Select a device by index. Returns False if index invalid."""
        if idx < 0 or idx >= len(self.devices):
            return False
        self.selected_device = self.devices[idx]
        return True

    def select_wipe_mode(self, mode: str):
        """mode: 'CLEAR', 'PURGE', or 'FIRMWARE_DELETION'"""
        assert mode in ("CLEAR", "PURGE", "FIRMWARE_DELETION")
        self.selected_mode = mode

    def get_available_modes(self) -> List[dict]:
        """
        Return list of wipe modes available for the selected device.
        Each entry: {id, name, description, time_estimate, recommended, warning}
        """
        if not self.selected_device:
            return []

        modes = []

        if self.selected_device.is_android:
            info = self.selected_device.android_device
            is_rooted = info.is_rooted if info else False

            if is_rooted:
                modes.append({
                    "id": "CLEAR",
                    "name": "Clear — Zero Overwrite",
                    "description": "Zero-fill userdata + wipe metadata (FBE keys destroyed).",
                    "time_estimate": "20-60 min",
                    "recommended": False,
                    "warning": None
                })
                modes.append({
                    "id": "PURGE",
                    "name": "Purge — Crypto + Random Overwrite",
                    "description": "Destroy TEE keys via metadata wipe, then random-fill userdata.",
                    "time_estimate": "30-90 min",
                    "recommended": True,
                    "warning": None
                })
                modes.append({
                    "id": "FIRMWARE_DELETION",
                    "name": "Firmware Erase — eMMC/UFS Secure Erase",
                    "description": "Hardware-level erase including wear-leveled blocks.",
                    "time_estimate": "2-10 min",
                    "recommended": True,
                    "warning": None
                })

            # Factory reset always available
            modes.append({
                "id": "FACTORY_RESET",
                "name": "Factory Reset (Recovery)",
                "description": "Triggers Android factory reset via recovery. Evicts TEE keys.",
                "time_estimate": "5-15 min",
                "recommended": not is_rooted,
                "warning": "Non-root: this is the only option that evicts hardware keys."
            })

        else:
            dev = self.selected_device.pc_device
            is_ssd = dev.is_ssd if dev else False

            modes.append({
                "id": "CLEAR",
                "name": "Clear — Zero Overwrite",
                "description": "Overwrites all sectors with zeros. NIST SP 800-88 Clear.",
                "time_estimate": "25-30 min (HDD) / 10-15 min (SSD)",
                "recommended": not is_ssd,
                "warning": "NOT recommended for SSDs — wear-leveling blocks are not covered." if is_ssd else None
            })
            modes.append({
                "id": "PURGE",
                "name": "Purge — Cryptographic Erase",
                "description": "AES-256 encrypt + key destruction + random overwrite. NIST Purge.",
                "time_estimate": "1-5 min (SSD) / 30-60 min (HDD)",
                "recommended": is_ssd,
                "warning": None
            })
            modes.append({
                "id": "FIRMWARE_DELETION",
                "name": "Firmware Deletion — ATA/NVMe Secure Erase",
                "description": "Firmware-level sanitize. Covers HPA, DCO, overprovisioned blocks.",
                "time_estimate": "3-5 min",
                "recommended": True,
                "warning": "May not work if ATA security is frozen. ZeroTrace will attempt unfreeze." if (dev and dev.hidden.security_frozen) else None
            })

        return modes

    def execute_wipe(self, progress_cb: Callable) -> WipeSession:
        """
        Run the wipe operation.
        progress_cb signature:
            For PC: (bytes_done: int, bytes_total: int, stage: str) -> None
            For Android: wrapped into (message: str) -> None

        Returns a WipeSession.
        """
        assert self.selected_device, "No device selected"
        assert self.selected_mode, "No wipe mode selected"

        session = WipeSession(
            device=self.selected_device,
            wipe_mode_str=self.selected_mode,
            wipe_result=None
        )

        if self.selected_device.is_android:
            # Android path
            mode_map = {
                "CLEAR":              AndroidWipeMode.CLEAR,
                "PURGE":              AndroidWipeMode.PURGE,
                "FIRMWARE_DELETION":  AndroidWipeMode.FIRMWARE_ERASE,
                "FACTORY_RESET":      AndroidWipeMode.FACTORY_RESET,
            }
            android_mode = mode_map.get(self.selected_mode, AndroidWipeMode.FACTORY_RESET)

            # Wrap progress callback for Android (string-only)
            def android_progress(msg: str):
                progress_cb(0, 1, msg)  # bytes are irrelevant for Android

            result = wipe_android_device(
                serial=self.selected_device.android_serial,
                mode=android_mode,
                progress_cb=android_progress
            )
            session.wipe_result = result

        else:
            # PC path — C++ core engine
            if not CORE_AVAILABLE:
                raise RuntimeError("zerotrace_core not loaded — cannot wipe PC drives")

            dev_info = self.selected_device.pc_device
            mode_map = {
                "CLEAR":              core.WipeMode.CLEAR,
                "PURGE":              core.WipeMode.PURGE,
                "FIRMWARE_DELETION":  core.WipeMode.FIRMWARE_DELETION,
            }
            wipe_mode = mode_map[self.selected_mode]

            if wipe_mode == core.WipeMode.CLEAR:
                result = core.wipe_clear(dev_info, progress_cb)
            elif wipe_mode == core.WipeMode.PURGE:
                result = core.wipe_purge(dev_info, progress_cb)
            else:
                # Firmware deletion — call wipe_firmware from the C++ side
                # (wipe_firmware is not yet in bindings — add it here)
                result = core.wipe_firmware(dev_info, progress_cb)  # Fixed from wipe_purge in spec

            session.wipe_result = result

        self.current_session = session
        return session

    def run_entropy_check(self, session: WipeSession) -> object:
        """
        Run post-wipe entropy analysis.
        Updates session.entropy_result in place.
        """
        if session.device.is_android:
            # Android entropy is already computed inside wipe_android_device
            android_result = session.wipe_result
            if hasattr(android_result, 'entropy_bits') and android_result.entropy_bits is not None:
                session.entropy_result = {
                    "entropy_bits": android_result.entropy_bits,
                    "state": android_result.entropy_state,
                    "wipe_verified": android_result.entropy_bits < 0.1 or android_result.entropy_bits > 7.5,
                    "source": "android_in_wipe"
                }
            else:
                session.entropy_result = {
                    "entropy_bits": None,
                    "state": "NOT_MEASURED",
                    "wipe_verified": None,
                    "source": "not_available"
                }
        else:
            # PC entropy via C++ core
            if not CORE_AVAILABLE:
                return None

            mode_map = {
                "CLEAR":              core.WipeMode.CLEAR,
                "PURGE":              core.WipeMode.PURGE,
                "FIRMWARE_DELETION":  core.WipeMode.FIRMWARE_DELETION,
            }
            wipe_mode = mode_map[session.wipe_mode_str]
            dev_path = session.device.pc_device.device_path
            entropy_result = core.analyze_entropy(dev_path, wipe_mode)
            session.entropy_result = entropy_result

        return session.entropy_result

    def compute_valuation(self, session: WipeSession) -> dict:
        """
        Compute e-waste valuation for the device.
        Uses SMART data for PC drives.
        """
        try:
            from valuation.valuator import EWasteValuator
        except ImportError:
            # Valuation not yet available
            return None

        valuator = EWasteValuator()

        if session.device.is_android:
            info = session.device.android_device
            valuation = valuator.estimate_android(info)
        else:
            dev = session.device.pc_device
            smart_dict = {
                "power_on_hours": dev.smart.power_on_hours,
                "reallocated_sector_count": dev.smart.reallocated_sector_count,
                "pending_sector_count": dev.smart.pending_sector_count,
                "temperature_celsius": dev.smart.temperature_celsius,
            }
            dev_dict = {
                "type": str(dev.type),
                "size_gb": dev.size_gb,
            }
            valuation = valuator.estimate_value(dev_dict, smart_dict)

        session.valuation = valuation
        return valuation

    def run_telemetry_benchmark(self, session: WipeSession, sample_count: int = 10000) -> dict:
        """
        Run the high-resolution Phase 5 RDTSC telemetry benchmark.
        """
        if session.device.is_android or not CORE_AVAILABLE:
            return {"error": "Telemetry benchmarking requires a PC block device and C++ core."}
            
        try:
            from research.analyzer import BehavioralAnalyzer, ResearchMetadata, collect_environment_metadata
            from research.dataset_builder import DatasetBuilder
            from research.telemetry_export import export_to_csv
        except ImportError as e:
            return {"error": f"Research module missing: {e}"}
            
        dev = session.device.pc_device
        dev_path = dev.device_path
        
        try:
            engine = core.TelemetryEngine(dev_path)
        except Exception as e:
            return {"error": f"Failed to initialize telemetry engine (O_DIRECT block access required): {e}"}
            
        # Collect pre-flight environment warnings
        env_meta = collect_environment_metadata()
        warnings = env_meta.pop("warnings", [])
        
        # Execute the scan with Repeated Trial Averaging
        TRIAL_COUNT = 3
        aggregated_latencies = []
        mean_cycles_sum = 0
        median_cycles_sum = 0
        std_dev_sum = 0
        
        for trial in range(TRIAL_COUNT):
            profile = engine.execute_telemetry_scan(start_lba=0, sample_count=sample_count)
            aggregated_latencies.extend(profile.raw_latencies)
            mean_cycles_sum += profile.mean_latency_cycles
            median_cycles_sum += profile.median_latency_cycles
            std_dev_sum += profile.std_deviation
            
        avg_mean = mean_cycles_sum / TRIAL_COUNT
        avg_median = median_cycles_sum / TRIAL_COUNT
        avg_std_dev = std_dev_sum / TRIAL_COUNT

        # Synthetic baselines for testing/demonstration since true baseline 
        # calibration requires physical chip knowledge we don't have simulated here.
        # In a real environment, engine.profile_entropy_* would be used.
        synthetic_erased_baseline = [avg_median * 0.8] * (sample_count * TRIAL_COUNT)
        synthetic_charged_baseline = [avg_median * 1.2] * (sample_count * TRIAL_COUNT)
        
        opcode_str = session.wipe_result.firmware_command_name if (session.wipe_result and hasattr(session.wipe_result, 'firmware_command_name')) else session.wipe_mode_str
        temp_c = str(dev.smart.temperature_celsius) if hasattr(dev, 'smart') and dev.smart else "Unknown"
        
        metadata = ResearchMetadata(
            vendor="Unknown Vendor",
            model=dev.model,
            firmware_version=dev.firmware_version,
            controller_type=str(dev.type),
            reported_capacity_gb=dev.size_gb,
            sanitize_completion_time_sec=session.wipe_result.duration_seconds if session.wipe_result else 0.0,
            post_wipe_entropy=session.entropy_result.get('entropy_bits', 0.0) if isinstance(session.entropy_result, dict) else (session.entropy_result.entropy_bits if hasattr(session.entropy_result, 'entropy_bits') else 0.0),
            kernel_version=env_meta.get("kernel_version", "Unknown"),
            cpu_model=env_meta.get("cpu_model", "Unknown"),
            cpu_governor=env_meta.get("cpu_governor", "Unknown"),
            ssd_temperature_c=temp_c,
            sanitize_opcode=opcode_str,
            benchmark_timestamp=env_meta.get("benchmark_timestamp", ""),
            trial_count=TRIAL_COUNT
        )
        
        analyzer = BehavioralAnalyzer(metadata)
        result = analyzer.evaluate_behavioral_consistency(
            post_wipe_latencies=aggregated_latencies,
            erased_baseline=synthetic_erased_baseline,
            charged_baseline=synthetic_charged_baseline
        )
        
        # Add profile telemetry data to the result for CSV export
        result["mean_latency_cycles"] = avg_mean
        result["median_latency_cycles"] = avg_median
        result["std_deviation"] = avg_std_dev
        result["warnings"] = warnings
        
        dataset = [result]
        export_to_csv(dataset)
        
        return result
