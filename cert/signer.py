# cert/signer.py
#
# PKI key management and digital signing.
#
# Key generation (run ONCE during ZeroTrace setup):
#   python3 -c "from cert.signer import generate_keypair; generate_keypair()"
#
# This creates:
#   cert/keys/zerotrace_private.pem  — 4096-bit RSA private key
#   cert/keys/zerotrace_public.pem   — corresponding public key

import os
import base64
import hashlib
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.backends import default_backend


# Paths relative to this file
_KEYS_DIR = Path(__file__).parent / "keys"
_PRIVATE_KEY_PATH = _KEYS_DIR / "zerotrace_private.pem"
_PUBLIC_KEY_PATH  = _KEYS_DIR / "zerotrace_public.pem"


def generate_keypair():
    """
    Generate a new RSA-4096 keypair and save to cert/keys/.
    Run this ONCE on the ZeroTrace build machine.
    The private key must then be kept ONLY on the USB drive.
    """
    _KEYS_DIR.mkdir(parents=True, exist_ok=True)

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=4096,
        backend=default_backend()
    )

    # Save private key (PEM, unencrypted — USB is the physical security boundary)
    with open(_PRIVATE_KEY_PATH, "wb") as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        ))

    # Save public key
    public_key = private_key.public_key()
    with open(_PUBLIC_KEY_PATH, "wb") as f:
        f.write(public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ))

    print(f"Keypair generated:")
    print(f"  Private: {_PRIVATE_KEY_PATH}")
    print(f"  Public:  {_PUBLIC_KEY_PATH}")
    print(f"  Fingerprint: {get_public_key_fingerprint()}")


def get_public_key_fingerprint(pubkey_path: str = None) -> str:
    """
    Returns SHA-256 fingerprint of the public key.
    Format: AA:BB:CC:DD:...
    """
    path = pubkey_path or str(_PUBLIC_KEY_PATH)
    with open(path, "rb") as f:
        pub_bytes = f.read()

    digest = hashlib.sha256(pub_bytes).hexdigest().upper()
    # Format as colon-separated pairs
    return ":".join(digest[i:i+2] for i in range(0, 32, 2))  # First 16 bytes


def sign_data(data: str) -> str:
    """
    Sign a string with the ZeroTrace private key.
    Returns Base64-encoded RSA-PSS signature.

    data: the string to sign (typically the hex certificate hash)
    """
    if not _PRIVATE_KEY_PATH.exists():
        raise FileNotFoundError(
            f"Private key not found at {_PRIVATE_KEY_PATH}. "
            "Run generate_keypair() first."
        )

    with open(_PRIVATE_KEY_PATH, "rb") as f:
        private_key = serialization.load_pem_private_key(
            f.read(),
            password=None,
            backend=default_backend()
        )

    signature = private_key.sign(
        data.encode('utf-8'),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH
        ),
        hashes.SHA256()
    )

    return base64.b64encode(signature).decode('utf-8')


def verify_signature(data: str, signature_b64: str, pubkey_path: str = None) -> bool:
    """
    Verify a signature against the public key.
    Returns True if valid, False if invalid.
    Never raises on signature mismatch — returns False instead.
    """
    path = pubkey_path or str(_PUBLIC_KEY_PATH)

    try:
        with open(path, "rb") as f:
            public_key = serialization.load_pem_public_key(
                f.read(),
                backend=default_backend()
            )

        signature = base64.b64decode(signature_b64)

        public_key.verify(
            signature,
            data.encode('utf-8'),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )
        return True

    except Exception:
        return False
