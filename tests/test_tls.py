"""Tests for crypto/tls.py — TLS Certificate Management (GopherS)."""

import ssl
import sys
import pytest
from pathlib import Path
from cryptography import x509

from crypto.tls import generate_self_signed_cert, load_or_create_tls_context, is_cert_valid
from crypto.pid import generate_pid


def _patch_tls_dir(tmp_path, monkeypatch):
    import crypto.tls as mod
    tls_dir = tmp_path / "tls"
    monkeypatch.setattr(mod, "TLS_DIR", tls_dir)


# Python 3.9 + LibreSSL on macOS does not support TLS 1.3
_TLS13_UNSUPPORTED = "LibreSSL" in ssl.OPENSSL_VERSION


class TestGenerateCert:
    """Self-signed certificate generation."""

    def test_creates_cert_and_key_files(self, tmp_path, monkeypatch):
        _patch_tls_dir(tmp_path, monkeypatch)
        pid = generate_pid()
        cert_path, key_path = generate_self_signed_cert(pid)
        assert cert_path.exists()
        assert key_path.exists()

    def test_cert_contains_pid_in_cn(self, tmp_path, monkeypatch):
        _patch_tls_dir(tmp_path, monkeypatch)
        pid = generate_pid()
        cert_path, _ = generate_self_signed_cert(pid)
        cert_data = cert_path.read_bytes()
        cert = x509.load_pem_x509_certificate(cert_data)
        cn = cert.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)[0].value
        assert pid["pid"][:16] in cn

    def test_cert_has_san_entries(self, tmp_path, monkeypatch):
        _patch_tls_dir(tmp_path, monkeypatch)
        pid = generate_pid()
        cert_path, _ = generate_self_signed_cert(pid, hostname="myhost")
        cert_data = cert_path.read_bytes()
        cert = x509.load_pem_x509_certificate(cert_data)
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        dns_names = san.value.get_values_for_type(x509.DNSName)
        assert "myhost" in dns_names
        assert "localhost" in dns_names

    def test_key_file_permissions(self, tmp_path, monkeypatch):
        _patch_tls_dir(tmp_path, monkeypatch)
        pid = generate_pid()
        _, key_path = generate_self_signed_cert(pid)
        perms = key_path.stat().st_mode & 0o777
        assert perms == 0o600

    def test_cert_is_valid(self, tmp_path, monkeypatch):
        _patch_tls_dir(tmp_path, monkeypatch)
        pid = generate_pid()
        cert_path, _ = generate_self_signed_cert(pid)
        assert is_cert_valid(cert_path) is True

    def test_nonexistent_cert_is_invalid(self):
        assert is_cert_valid(Path("/nonexistent/cert.pem")) is False


class TestTLSContext:
    """TLS context creation."""

    @pytest.mark.skipif(_TLS13_UNSUPPORTED, reason="TLS 1.3 not supported with LibreSSL")
    def test_load_or_create_returns_ssl_context(self, tmp_path, monkeypatch):
        _patch_tls_dir(tmp_path, monkeypatch)
        pid = generate_pid()
        ctx = load_or_create_tls_context(pid)
        assert isinstance(ctx, ssl.SSLContext)

    @pytest.mark.skipif(_TLS13_UNSUPPORTED, reason="TLS 1.3 not supported with LibreSSL")
    def test_tls_context_enforces_tls_13(self, tmp_path, monkeypatch):
        _patch_tls_dir(tmp_path, monkeypatch)
        pid = generate_pid()
        ctx = load_or_create_tls_context(pid)
        assert ctx.minimum_version == ssl.TLSVersion.TLSv1_3

    @pytest.mark.skipif(_TLS13_UNSUPPORTED, reason="TLS 1.3 not supported with LibreSSL")
    def test_idempotent_creation(self, tmp_path, monkeypatch):
        _patch_tls_dir(tmp_path, monkeypatch)
        pid = generate_pid()
        ctx1 = load_or_create_tls_context(pid)
        ctx2 = load_or_create_tls_context(pid)
        assert isinstance(ctx1, ssl.SSLContext)
        assert isinstance(ctx2, ssl.SSLContext)
