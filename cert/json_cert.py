# cert/json_cert.py
#
# Builds the JSON certificate from a WipeSession.
# The JSON is the canonical form — the PDF is derived from it.
# The digital signature covers the JSON content.

import json
import uuid
import hashlib
import time
from datetime import datetime, timezone
from typing import Optional


ZEROTRACE_VERSION = "1.0.0"
NIST_STANDARD     = "NIST SP 800-88 Rev.1"


def build_certificate_dict(session) -> dict:
    """
    Build the full certificate dictionary from a WipeSession.
    This is the unsigned version — sign_and_finalize() adds the signature.

    session: ui.orchestrator.WipeSession
    """
    cert = {
        "certificate_id":   str(uuid.uuid4()),
        "zerotrace_version": ZEROTRACE_VERSION,
        "nist_compliance":   NIST_STANDARD,
        "generated_at":      datetime.now(timezone.utc).isoformat(),
        "session_start":     _epoch_to_iso(session.session_start),
    }

    # ── Device section ────────────────────────────────────────────────────
    dev = session.device

    if dev.is_android:
        info = dev.android_device
        cert["device"] = {
            "type":              "ANDROID",
            "manufacturer":      info.manufacturer,
            "model":             info.model,
            "serial":            info.serial,
            "android_version":   info.android_version,
            "sdk_version":       info.sdk_version,
            "build_id":          info.build_id,
            "storage_type":      info.storage_type.value,
            "userdata_size_gb":  round(info.userdata_size_bytes / (1024**3), 2) if info.userdata_size_bytes else 0,
            "encryption_state":  info.encryption_state.value,
            "tee_backed_keys":   info.tee_backed_keys,
            "bootloader_locked": not info.bootloader_unlocked,
        }
    else:
        pc = dev.pc_device
        type_names = {0: "HDD", 1: "SSD_SATA", 2: "SSD_NVME", 3: "USB_DRIVE", 4: "UNKNOWN"}
        cert["device"] = {
            "type":             type_names.get(int(pc.type), "UNKNOWN"),
            "model":            pc.model,
            "serial":           pc.serial,
            "firmware":         pc.firmware_version,
            "size_gb":          round(pc.size_gb, 2),
            "total_lbas":       pc.total_lbas,
            "is_ssd":           pc.is_ssd,
            "smart": {
                "health":                    {0: "PASSED", 1: "WARNING", 2: "FAILED", 3: "UNKNOWN"}.get(int(pc.smart.overall_health), "UNKNOWN"),
                "power_on_hours":            pc.smart.power_on_hours,
                "temperature_celsius":       pc.smart.temperature_celsius,
                "reallocated_sector_count":  pc.smart.reallocated_sector_count,
                "pending_sector_count":      pc.smart.pending_sector_count,
            },
        }

    # ── Wipe section ──────────────────────────────────────────────────────
    wr = session.wipe_result

    if dev.is_android:
        # wr is AndroidWipeResult
        cert["wipe"] = {
            "mode":                      wr.wipe_mode.value,
            "start":                     _epoch_to_iso(wr.start_epoch),
            "end":                       _epoch_to_iso(wr.end_epoch),
            "duration_seconds":          wr.duration_seconds,
            "success":                   wr.success,
            "is_rooted":                 wr.is_rooted,
            "userdata_wiped":            wr.userdata_wiped,
            "metadata_wiped":            wr.metadata_wiped,
            "tee_keys_invalidated":      wr.tee_keys_invalidated,
            "hardware_secure_erase":     wr.hardware_secure_erase_used,
            "factory_reset_triggered":   wr.factory_reset_triggered,
            "coverage":                  wr.coverage,
            "hidden_areas_covered":      wr.metadata_wiped or wr.hardware_secure_erase_used,
            "warnings":                  wr.warnings,
            "step_log":                  wr.step_log,
        }
    else:
        # wr is zerotrace_core.WipeResult (C++ object)
        cert["wipe"] = {
            "mode":                      session.wipe_mode_str,
            "start":                     _epoch_to_iso(wr.start_epoch),
            "end":                       _epoch_to_iso(wr.end_epoch),
            "duration_seconds":          wr.duration_seconds,
            "success":                   wr.success,
            "hpa_removed":               wr.hpa_removed,
            "dco_restored":              wr.dco_restored,
            "hidden_areas_covered":      wr.hidden_areas_covered,
            "firmware_command_used":     wr.firmware_command_used,
            "firmware_command_name":     wr.firmware_command_name,
            "sha256_pre_wipe":           wr.sha256_pre_wipe,
            "sha256_post_wipe":          wr.sha256_post_wipe,
            "error_message":             wr.error_message,
        }

    # ── Entropy section ────────────────────────────────────────────────────
    er = session.entropy_result
    if er is None:
        cert["verification"] = {"status": "NOT_PERFORMED"}
    elif isinstance(er, dict):
        cert["verification"] = {
            "entropy_bits":       er.get("entropy_bits"),
            "state":              er.get("state", "UNKNOWN"),
            "wipe_verified":      er.get("wipe_verified", False),
            "blocks_sampled":     er.get("blocks_sampled", 0),
            "sample_coverage_pct": er.get("sample_coverage_pct", 0.0),
        }
    else:
        # C++ EntropyResult object
        cert["verification"] = {
            "entropy_bits":       round(er.entropy_bits, 6),
            "state":              er.state,
            "wipe_verified":      er.wipe_verified,
            "blocks_sampled":     er.blocks_sampled,
            "sample_coverage_pct": round(er.sample_coverage_pct, 2),
        }

    # ── Valuation section ──────────────────────────────────────────────────
    if session.valuation:
        cert["valuation"] = session.valuation

    return cert


def sign_and_finalize(cert_dict: dict) -> dict:
    """
    Add certificate_hash and digital signature to the certificate dict.
    Returns the finalized cert dict ready for JSON serialization.

    IMPORTANT: The dict must NOT contain "certificate_hash" or "signature"
    keys before calling this — they are added here.
    """
    from .signer import sign_data, get_public_key_fingerprint

    # Canonical JSON serialization (sorted keys, no whitespace)
    # This is what gets hashed and signed
    canonical = json.dumps(cert_dict, sort_keys=True, separators=(',', ':'))
    cert_hash = hashlib.sha256(canonical.encode('utf-8')).hexdigest()

    # Sign the hash
    signature = sign_data(cert_hash)
    fingerprint = get_public_key_fingerprint()

    # Add to certificate
    cert_dict["certificate_hash"]        = cert_hash
    cert_dict["signature"]               = signature
    cert_dict["public_key_fingerprint"]  = fingerprint

    return cert_dict


def serialize_to_json(cert_dict: dict) -> str:
    """Serialize the finalized certificate to pretty-printed JSON string."""
    return json.dumps(cert_dict, indent=2, default=str)


def _epoch_to_iso(epoch: int) -> str:
    if not epoch:
        return "unknown"
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()
