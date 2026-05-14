# valuation/valuator.py
#
# E-waste valuation module.
# Estimates resale/recycling value of a drive or Android device
# based on its specs and health data collected during the pre-wipe scan.
# This is an estimate — not a guarantee of market price.

from dataclasses import dataclass
from typing import Optional


@dataclass
class ValuationResult:
    base_value_inr: float
    health_multiplier: float
    certification_bonus_pct: float
    estimated_value_inr: float
    condition: str          # "EXCELLENT" / "GOOD" / "FAIR" / "POOR"
    recommendation: str


class EWasteValuator:
    """
    Estimates device resale value in INR (Indian Rupee).
    Prices are approximate secondhand market values as of 2025-2026.
    Adjust BASE_VALUES dict as needed.
    """

    # Base resale values in INR for a like-new, fully functional device
    # Values from approximate Indian secondhand market (OLX, Quikr, etc.)
    BASE_VALUES_HDD = {
        160:  150,
        250:  200,
        320:  250,
        500:  350,
        1000: 500,    # 1TB
        2000: 800,    # 2TB
        4000: 1400,   # 4TB
    }
    BASE_VALUES_SSD_SATA = {
        120:  800,
        240:  1200,
        480:  1800,
        500:  1900,
        960:  3000,
        1000: 3200,   # 1TB
    }
    BASE_VALUES_SSD_NVME = {
        256:  1500,
        512:  2500,
        1000: 4000,   # 1TB
        2000: 7000,   # 2TB
    }
    BASE_VALUES_ANDROID = {
        # Estimated value by Android version (proxy for device generation)
        14: 8000,
        13: 5000,
        12: 3000,
        11: 1500,
        10: 800,
    }

    # 15% premium for certified-wipe device (buyer has audit trail)
    CERTIFICATION_BONUS = 0.15

    def estimate_value(self, device_info: dict, smart_data: dict) -> dict:
        """
        Estimate value for a PC storage device.

        device_info: dict with keys "type" (DriveType string), "size_gb"
        smart_data: dict with keys "power_on_hours", "reallocated_sector_count",
                    "pending_sector_count", "temperature_celsius"
        """
        drive_type = str(device_info.get("type", "")).upper()
        size_gb = float(device_info.get("size_gb", 0))

        base = self._lookup_base_value(drive_type, size_gb)
        health_mult = self._compute_health_multiplier(smart_data)
        cert_bonus = 1.0 + self.CERTIFICATION_BONUS
        final = base * health_mult * cert_bonus

        condition = self._classify_condition(health_mult)
        recommendation = self._get_recommendation(health_mult, final)

        return {
            "base_value_inr":        round(base, 0),
            "health_multiplier":     round(health_mult, 2),
            "certification_bonus":   f"{int(self.CERTIFICATION_BONUS * 100)}%",
            "estimated_value_inr":   round(final, 0),
            "condition":             condition,
            "recommendation":        recommendation,
        }

    def estimate_android(self, android_info) -> dict:
        """
        Estimate value for an Android device.
        android_info: AndroidDeviceInfo dataclass
        """
        sdk = android_info.sdk_version

        # Android version from SDK
        version_map = {34: 14, 33: 13, 32: 12, 31: 12, 30: 11, 29: 10}
        android_ver = version_map.get(sdk, max(10, sdk - 19))

        # Find closest base value
        base = 500  # Default for unknown/very old
        for ver in sorted(self.BASE_VALUES_ANDROID.keys(), reverse=True):
            if android_ver >= ver:
                base = self.BASE_VALUES_ANDROID[ver]
                break

        # Health factors for Android
        health_mult = 1.0

        # Root reduces resale value slightly (some buyers don't want rooted devices)
        if android_info.is_rooted:
            health_mult *= 0.90

        # Locked bootloader is preferred for resale
        if android_info.bootloader_unlocked:
            health_mult *= 0.92

        cert_bonus = 1.0 + self.CERTIFICATION_BONUS
        final = base * health_mult * cert_bonus
        condition = self._classify_condition(health_mult)
        recommendation = self._get_recommendation(health_mult, final)

        return {
            "base_value_inr":        round(base, 0),
            "health_multiplier":     round(health_mult, 2),
            "certification_bonus":   f"{int(self.CERTIFICATION_BONUS * 100)}%",
            "estimated_value_inr":   round(final, 0),
            "condition":             condition,
            "recommendation":        recommendation,
            "note":                  "Android valuation is approximate. Actual price depends on device condition.",
        }

    def _lookup_base_value(self, drive_type: str, size_gb: float) -> float:
        if "NVME" in drive_type:
            table = self.BASE_VALUES_SSD_NVME
        elif "SSD" in drive_type or "SATA" in drive_type:
            table = self.BASE_VALUES_SSD_SATA
        else:
            table = self.BASE_VALUES_HDD

        # Find closest size tier
        sizes = sorted(table.keys())
        for s in sizes:
            if size_gb <= s * 1.05:  # 5% tolerance
                return float(table[s])

        # Larger than any tier — extrapolate from largest
        return float(table[max(sizes)])

    def _compute_health_multiplier(self, smart: dict) -> float:
        mult = 1.0
        hours = smart.get("power_on_hours", 0)
        realloc = smart.get("reallocated_sector_count", 0)
        pending = smart.get("pending_sector_count", 0)

        # Hours-based depreciation
        if hours >= 40000:
            mult *= 0.20
        elif hours >= 20000:
            mult *= 0.35
        elif hours >= 10000:
            mult *= 0.55
        elif hours >= 5000:
            mult *= 0.75
        elif hours >= 2000:
            mult *= 0.90

        # Reallocated sector penalty
        if realloc > 100:
            mult *= 0.30
        elif realloc > 50:
            mult *= 0.50
        elif realloc > 10:
            mult *= 0.70
        elif realloc > 0:
            mult *= 0.85

        # Pending sector penalty
        if pending > 0:
            mult *= 0.80

        return max(0.05, mult)  # Never below 5% (scrap value)

    def _classify_condition(self, mult: float) -> str:
        if mult >= 0.90:  return "EXCELLENT"
        if mult >= 0.70:  return "GOOD"
        if mult >= 0.50:  return "FAIR"
        if mult >= 0.25:  return "POOR"
        return "SCRAP"

    def _get_recommendation(self, mult: float, value_inr: float) -> str:
        if mult >= 0.70:
            return "Suitable for resale on secondhand market (OLX, Quikr)"
        elif mult >= 0.40:
            return "Suitable for low-grade reuse, bulk resale, or parts"
        elif mult >= 0.20:
            return "Recommend responsible e-waste recycling at certified facility"
        else:
            return "Scrap value only — send to certified e-waste recycler"
