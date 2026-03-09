"""
REFInet Pillar — TLS Certificate Management (GopherS)

Generates self-signed X.509 certificates for encrypted Gopher connections.
The certificate includes the Pillar's PID in the Common Name for TOFU
(Trust On First Use) verification.

TLS 1.3 minimum is enforced for all encrypted connections.
"""

from __future__ import annotations

import ipaddress
import ssl
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from core.config import TLS_DIR, ensure_dirs

logger = logging.getLogger("refinet.tls")


def generate_self_signed_cert(pid_data: dict, hostname: str = "localhost",
                               validity_days: int = 365) -> tuple[Path, Path]:
    """
    Generate a self-signed X.509 certificate for GopherS.

    The certificate's CN includes the Pillar's PID for identification.
    SANs include the hostname and localhost for local connections.

    Args:
        pid_data: PID data dict containing 'pid' and 'public_key'
        hostname: Server hostname for SAN
        validity_days: Certificate validity period

    Returns:
        Tuple of (cert_path, key_path)
    """
    ensure_dirs()
    TLS_DIR.mkdir(parents=True, exist_ok=True)

    cert_path = TLS_DIR / "cert.pem"
    key_path = TLS_DIR / "key.pem"

    # Generate RSA key for TLS (Ed25519 not widely supported in TLS)
    tls_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    pid_short = pid_data["pid"][:16]
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, f"REFInet Pillar {pid_short}"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "REFInet"),
    ])

    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(tls_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=validity_days))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName(hostname),
                x509.DNSName("localhost"),
                x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
            ]),
            critical=False,
        )
        .sign(tls_key, hashes.SHA256())
    )

    # Write certificate
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    # Write private key (file permissions set to owner-only)
    key_path.write_bytes(
        tls_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    key_path.chmod(0o600)

    logger.info(f"[TLS] Self-signed certificate generated: CN=REFInet Pillar {pid_short}")
    return cert_path, key_path


def load_or_create_tls_context(pid_data: dict,
                                hostname: str = "localhost") -> ssl.SSLContext:
    """
    Load existing TLS cert/key or generate new ones, then create an SSLContext.

    Enforces TLS 1.3 minimum.

    Returns:
        Configured ssl.SSLContext for server use
    """
    cert_path = TLS_DIR / "cert.pem"
    key_path = TLS_DIR / "key.pem"

    if not cert_path.exists() or not key_path.exists():
        cert_path, key_path = generate_self_signed_cert(pid_data, hostname)

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.load_cert_chain(str(cert_path), str(key_path))

    logger.info("[TLS] SSLContext created with TLS 1.3 minimum")
    return ctx


def is_cert_valid(cert_path: Path = None) -> bool:
    """Check if the existing certificate is still valid."""
    if cert_path is None:
        cert_path = TLS_DIR / "cert.pem"
    if not cert_path.exists():
        return False
    try:
        cert_data = cert_path.read_bytes()
        cert = x509.load_pem_x509_certificate(cert_data)
        now = datetime.now(timezone.utc)
        return cert.not_valid_before_utc <= now <= cert.not_valid_after_utc
    except Exception:
        return False
