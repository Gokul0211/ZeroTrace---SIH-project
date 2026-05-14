# cert/generator.py
#
# Main entry point for certificate generation.
# Called by the TUI (Phase 3) after wipe + entropy are complete.
# Returns (pdf_path, json_path) tuple.

import os
import json
from datetime import datetime
from pathlib import Path

from .json_cert import build_certificate_dict, sign_and_finalize, serialize_to_json
from .pdf_cert import generate_pdf


# Where to save certificates
# In the bootable environment, this is the ZeroTrace USB export directory.
# During development, saves to current directory.
CERT_OUTPUT_DIR = Path(os.environ.get("ZEROTRACE_CERT_DIR", "/mnt/usb_export"))


def generate_certificate_pair(session) -> tuple:
    """
    Generate both PDF and JSON certificates for a completed wipe session.
    Returns (pdf_path, json_path) as strings.

    Raises on failure — caller should catch and display error.
    """
    # Ensure output directory exists
    CERT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Build filename from device serial and timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    serial_tag = _get_serial_tag(session)
    base_name = f"zerotrace_cert_{serial_tag}_{timestamp}"

    json_path = str(CERT_OUTPUT_DIR / f"{base_name}.json")
    pdf_path  = str(CERT_OUTPUT_DIR / f"{base_name}.pdf")

    # Build and sign the certificate
    cert_dict = build_certificate_dict(session)
    cert_dict = sign_and_finalize(cert_dict)

    # Write JSON
    with open(json_path, "w") as f:
        f.write(serialize_to_json(cert_dict))

    # Write PDF (derived from the same cert_dict)
    generate_pdf(cert_dict, pdf_path)

    return pdf_path, json_path


def _get_serial_tag(session) -> str:
    """Extract first 8 chars of device serial for filename."""
    try:
        dev = session.device
        if dev.is_android and dev.android_device:
            serial = dev.android_device.serial or dev.android_serial or "UNKNOWN"
        elif dev.pc_device:
            serial = dev.pc_device.serial or "UNKNOWN"
        else:
            serial = "UNKNOWN"
        # Remove non-alphanumeric chars and truncate
        serial = ''.join(c for c in serial if c.isalnum())
        return serial[:8].upper() if serial else "UNKNOWN"
    except Exception:
        return "UNKNOWN"
