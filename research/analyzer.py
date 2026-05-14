# research/analyzer.py
import numpy as np
import scipy.stats as stats
from dataclasses import dataclass

@dataclass
class ResearchMetadata:
    vendor: str
    model: str
    firmware_version: str
    controller_type: str
    reported_capacity_gb: float
    sanitize_completion_time_sec: float
    post_wipe_entropy: float
    # New Session Metadata
    kernel_version: str
    cpu_model: str
    cpu_governor: str
    ssd_temperature_c: str
    sanitize_opcode: str
    benchmark_timestamp: str
    trial_count: int

def collect_environment_metadata() -> dict:
    """Collects lightweight environment metadata and pre-flight warnings."""
    import platform
    import subprocess
    import time
    import os

    meta = {
        "kernel_version": platform.release(),
        "cpu_model": "Unknown",
        "cpu_governor": "Unknown",
        "benchmark_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "warnings": []
    }

    # CPU Model
    try:
        with open("/proc/cpuinfo", "r") as f:
            for line in f:
                if "model name" in line:
                    meta["cpu_model"] = line.split(":")[1].strip()
                    break
    except:
        pass

    # CPU Governor Check
    try:
        gov_path = "/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"
        if os.path.exists(gov_path):
            with open(gov_path, "r") as f:
                gov = f.read().strip()
                meta["cpu_governor"] = gov
                if gov != "performance":
                    meta["warnings"].append(f"CPU governor is '{gov}', not 'performance' (timing variance likely)")
    except:
        pass

    # Background Disk Activity Check (Very lightweight check using vmstat)
    try:
        res = subprocess.run(["vmstat", "1", "2"], capture_output=True, text=True)
        lines = res.stdout.strip().split('\n')
        if len(lines) >= 4:
            # Check the 'bo' (blocks out) column on the second sample
            parts = lines[3].split()
            if len(parts) > 10:
                blocks_out = int(parts[10])
                if blocks_out > 100:
                    meta["warnings"].append(f"Background disk activity detected ({blocks_out} blocks out)")
    except:
        pass

    return meta

class BehavioralAnalyzer:
    def __init__(self, metadata: ResearchMetadata):
        self.metadata = metadata
        self.findings = []

    def evaluate_behavioral_consistency(self, post_wipe_latencies: list, erased_baseline: list, charged_baseline: list) -> dict:
        """
        Uses a two-sample K-S test to compare the post-wipe read latency distribution
        against the established physical baselines.
        """
        if not post_wipe_latencies or not erased_baseline or not charged_baseline:
            return {"error": "Insufficient data for KS-test"}

        # Compare post-wipe to physically erased baseline
        ks_stat_erased, p_val_erased = stats.ks_2samp(post_wipe_latencies, erased_baseline)
        
        # Compare post-wipe to physically charged baseline
        ks_stat_charged, p_val_charged = stats.ks_2samp(post_wipe_latencies, charged_baseline)
        
        # Identify potentially anomalous behavior: 
        # The distribution strongly rejects the erased hypothesis (p < 0.05) 
        # while failing to reject the charged hypothesis (p > 0.05).
        is_anomalous = bool(p_val_charged > 0.05 and p_val_erased < 0.05)
        
        result = {
            "vendor": self.metadata.vendor,
            "model": self.metadata.model,
            "firmware": self.metadata.firmware_version,
            "sanitize_duration": self.metadata.sanitize_completion_time_sec,
            "post_wipe_entropy": self.metadata.post_wipe_entropy,
            "is_anomalous": is_anomalous,
            "p_value_vs_erased": p_val_erased,
            "p_value_vs_charged": p_val_charged,
            "mean_cycles": np.mean(post_wipe_latencies),
            "std_dev_cycles": np.std(post_wipe_latencies),
            "kernel_version": self.metadata.kernel_version,
            "cpu_model": self.metadata.cpu_model,
            "cpu_governor": self.metadata.cpu_governor,
            "ssd_temperature_c": self.metadata.ssd_temperature_c,
            "sanitize_opcode": self.metadata.sanitize_opcode,
            "benchmark_timestamp": self.metadata.benchmark_timestamp,
            "trial_count": self.metadata.trial_count
        }
        
        self.findings.append(result)
        return result
