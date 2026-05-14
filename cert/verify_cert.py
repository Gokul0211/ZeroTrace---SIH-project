#!/usr/bin/env python3
# cert/verify_cert.py
#
# ZeroTrace Certificate Verification Tool
# Standalone — no ZeroTrace installation required.
# Only dependency: pip install cryptography
#
# Usage:
#   python3 verify_cert.py <certificate.json> [zerotrace_public.pem]
#
# If no public key path is provided, downloads the official key from GitHub
# (requires internet) or looks for zerotrace_public.pem in the same directory.

import sys
import json
import hashlib
import base64
import os
from pathlib import Path

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.backends import default_backend
except ImportError:
    print("ERROR: 'cryptography' package not installed.")
    print("Install with: pip install cryptography")
    sys.exit(1)


def verify_certificate(cert_path: str, pubkey_path: str) -> bool:
    """
    Verify a ZeroTrace certificate.
    Returns True if valid and untampered, False otherwise.
    Prints detailed results to stdout.
    """
    print("=" * 60)
    print("  ZeroTrace Certificate Verification")
    print("=" * 60)

    # ── Load certificate ──────────────────────────────────────────────────
    try:
        with open(cert_path, "r") as f:
            cert = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: Certificate file not found: {cert_path}")
        return False
    except json.JSONDecodeError as e:
        print(f"ERROR: Certificate is not valid JSON: {e}")
        return False

    print(f"\nCertificate ID:  {cert.get('certificate_id', 'N/A')}")
    print(f"Generated at:    {cert.get('generated_at', 'N/A')}")
    print(f"ZeroTrace ver:   {cert.get('zerotrace_version', 'N/A')}")

    # ── Extract and remove signature fields ───────────────────────────────
    stored_signature   = cert.pop("signature", None)
    stored_cert_hash   = cert.pop("certificate_hash", None)
    stored_fingerprint = cert.pop("public_key_fingerprint", None)

    if not stored_signature or not stored_cert_hash:
        print("\nFAIL: Certificate is missing signature or hash fields.")
        print("      This certificate may have been manually edited or is corrupt.")
        return False

    # ── Step 1: Verify certificate hash ───────────────────────────────────
    print("\n── Step 1: Certificate Hash ─────────────────────────")
    canonical = json.dumps(cert, sort_keys=True, separators=(',', ':'))
    computed_hash = hashlib.sha256(canonical.encode('utf-8')).hexdigest()

    if computed_hash == stored_cert_hash:
        print(f"  ✓  Hash MATCHES")
        print(f"     Stored:   {stored_cert_hash}")
        print(f"     Computed: {computed_hash}")
    else:
        print(f"  ✗  Hash MISMATCH — certificate data has been altered!")
        print(f"     Stored:   {stored_cert_hash}")
        print(f"     Computed: {computed_hash}")
        return False

    # ── Step 2: Verify digital signature ──────────────────────────────────
    print("\n── Step 2: Digital Signature ────────────────────────")

    # Load public key
    try:
        with open(pubkey_path, "rb") as f:
            public_key = serialization.load_pem_public_key(
                f.read(),
                backend=default_backend()
            )
    except FileNotFoundError:
        print(f"  ERROR: Public key not found: {pubkey_path}")
        return False
    except Exception as e:
        print(f"  ERROR: Cannot load public key: {e}")
        return False

    # Verify public key fingerprint
    with open(pubkey_path, "rb") as f:
        pub_bytes = f.read()
    import hashlib
    computed_fp_raw = hashlib.sha256(pub_bytes).hexdigest().upper()
    computed_fp = ":".join(computed_fp_raw[i:i+2] for i in range(0, 32, 2))

    if stored_fingerprint:
        if computed_fp == stored_fingerprint:
            print(f"  ✓  Public key fingerprint matches")
        else:
            print(f"  ⚠  Public key fingerprint mismatch")
            print(f"     Certificate says: {stored_fingerprint}")
            print(f"     Your key:         {computed_fp}")
            print(f"     Proceeding with signature check anyway...")

    # Verify RSA-PSS signature
    try:
        signature_bytes = base64.b64decode(stored_signature)
        public_key.verify(
            signature_bytes,
            stored_cert_hash.encode('utf-8'),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )
        print(f"  ✓  Signature VALID — certificate is authentic ZeroTrace output")
    except Exception as e:
        print(f"  ✗  Signature INVALID — {e}")
        print(f"     This certificate was NOT signed by the ZeroTrace private key.")
        print(f"     It may be fabricated or signed by a different key.")
        return False

    # ── Step 3: Summary ───────────────────────────────────────────────────
    print("\n── Certificate Summary ──────────────────────────────")

    dev = cert.get("device", {})
    wipe = cert.get("wipe", {})
    ver = cert.get("verification", {})

    print(f"  Device:    {dev.get('model', dev.get('manufacturer', 'N/A'))} — {dev.get('type', 'N/A')}")
    print(f"  Serial:    {dev.get('serial', 'N/A')}")
    print(f"  Mode:      {wipe.get('mode', 'N/A')}")
    print(f"  Duration:  {wipe.get('duration_seconds', 'N/A')} seconds")
    print(f"  Verified:  {'YES' if ver.get('wipe_verified') else 'NO / NOT MEASURED'}")

    entropy = ver.get("entropy_bits")
    if entropy is not None:
        print(f"  Entropy:   {entropy:.6f} bits/byte  ({ver.get('state', 'N/A')})")

    print("\n" + "=" * 60)
    print("  RESULT: CERTIFICATE IS VALID AND AUTHENTIC ✓")
    print("=" * 60)
    return True


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 verify_cert.py <certificate.json> [public_key.pem]")
        print("       If no public key given, looks for zerotrace_public.pem in current directory.")
        sys.exit(1)

    cert_path = sys.argv[1]

    if len(sys.argv) >= 3:
        pubkey_path = sys.argv[2]
    else:
        # Look in same directory as certificate, then current directory
        cert_dir = Path(cert_path).parent
        candidates = [
            cert_dir / "zerotrace_public.pem",
            Path("zerotrace_public.pem"),
            Path(__file__).parent / "keys" / "zerotrace_public.pem"
        ]
        pubkey_path = None
        for c in candidates:
            if c.exists():
                pubkey_path = str(c)
                break

        if not pubkey_path:
            print("ERROR: zerotrace_public.pem not found.")
            print("Download from: https://github.com/zerotrace/zerotrace/releases")
            print("Or specify path: python3 verify_cert.py cert.json /path/to/public.pem")
            sys.exit(1)

    success = verify_certificate(cert_path, pubkey_path)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
