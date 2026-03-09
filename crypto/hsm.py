"""
REFInet Pillar — Hardware Security Module (HSM) Integration

Provides PKCS#11 support for hardware-backed key storage and signing.
When an HSM is available, private keys never leave the hardware device.

Requires: python-pkcs11 (optional dependency)

Falls back gracefully to software keys when HSM is not available.

Usage:
    hsm = HSMKeyStore("/usr/lib/softhsm/libsofthsm2.so", "refinet", "1234")
    if hsm.is_available():
        pid_data = hsm.generate_keypair("pillar-main")
        signature = hsm.sign(b"data", "pillar-main")
    else:
        # Fall back to software keys
        ...
"""

from __future__ import annotations

import hashlib
import logging
import time

logger = logging.getLogger("refinet.hsm")

# Optional dependency — graceful fallback
try:
    import pkcs11
    from pkcs11 import KeyType, ObjectClass, Mechanism
    _PKCS11_AVAILABLE = True
except ImportError:
    _PKCS11_AVAILABLE = False


class HSMKeyStore:
    """
    PKCS#11-based hardware key store for Ed25519 operations.

    Wraps a PKCS#11 library (e.g., SoftHSM, YubiKey, Nitrokey) to
    perform key generation and signing on the hardware device.
    """

    def __init__(self, pkcs11_lib_path: str, token_label: str, pin: str):
        """
        Initialize HSM connection.

        Args:
            pkcs11_lib_path: Path to the PKCS#11 shared library
            token_label: HSM token label
            pin: User PIN for the token
        """
        self._lib_path = pkcs11_lib_path
        self._token_label = token_label
        self._pin = pin
        self._lib = None
        self._token = None
        self._initialized = False

        if _PKCS11_AVAILABLE:
            try:
                self._lib = pkcs11.lib(pkcs11_lib_path)
                self._token = self._lib.get_token(token_label=token_label)
                self._initialized = True
                logger.info(f"[HSM] Connected to token: {token_label}")
            except Exception as e:
                logger.warning(f"[HSM] Failed to connect: {e}")

    def is_available(self) -> bool:
        """Check if HSM is available and initialized."""
        return self._initialized and _PKCS11_AVAILABLE

    def generate_keypair(self, label: str) -> dict:
        """
        Generate an Ed25519 keypair on the HSM.

        Args:
            label: Key label for identification

        Returns:
            PID data dict with key_store="hsm"
        """
        if not self.is_available():
            raise RuntimeError("HSM not available")

        with self._token.open(rw=True, user_pin=self._pin) as session:
            # Generate Ed25519 keypair on hardware
            # Note: Ed25519 support in PKCS#11 requires CKM_EDDSA
            pub_key, priv_key = session.generate_keypair(
                KeyType.EC_EDWARDS,
                curve="ed25519",
                label=label,
                store=True,
            )

            # Extract public key bytes
            pub_bytes = bytes(pub_key[pkcs11.Attribute.EC_POINT])
            # Remove DER encoding wrapper if present
            if len(pub_bytes) > 32:
                pub_bytes = pub_bytes[-32:]

            pid_hash = hashlib.sha256(pub_bytes).hexdigest()

            return {
                "pid": pid_hash,
                "public_key": pub_bytes.hex(),
                "private_key": {"key_store": "hsm", "label": label,
                                "token": self._token_label},
                "created_at": int(time.time()),
                "protocol": "REFInet-v0.2",
                "key_store": "hsm",
            }

    def sign(self, data: bytes, key_label: str) -> bytes:
        """
        Sign data using a key stored on the HSM.

        Args:
            data: Data bytes to sign
            key_label: Label of the signing key

        Returns:
            Signature bytes
        """
        if not self.is_available():
            raise RuntimeError("HSM not available")

        with self._token.open(user_pin=self._pin) as session:
            priv_key = session.get_key(
                object_class=ObjectClass.PRIVATE_KEY,
                label=key_label,
            )
            return priv_key.sign(data, mechanism=Mechanism.EDDSA)

    def get_public_key(self, key_label: str) -> bytes:
        """
        Retrieve a public key from the HSM.

        Args:
            key_label: Label of the key

        Returns:
            Public key bytes (32 bytes for Ed25519)
        """
        if not self.is_available():
            raise RuntimeError("HSM not available")

        with self._token.open(user_pin=self._pin) as session:
            pub_key = session.get_key(
                object_class=ObjectClass.PUBLIC_KEY,
                label=key_label,
            )
            pub_bytes = bytes(pub_key[pkcs11.Attribute.EC_POINT])
            if len(pub_bytes) > 32:
                pub_bytes = pub_bytes[-32:]
            return pub_bytes

    def list_keys(self) -> list[dict]:
        """List all Ed25519 keys stored on the HSM."""
        if not self.is_available():
            return []

        keys = []
        with self._token.open(user_pin=self._pin) as session:
            for key in session.get_objects({
                pkcs11.Attribute.CLASS: ObjectClass.PUBLIC_KEY,
            }):
                try:
                    label = key[pkcs11.Attribute.LABEL]
                    pub_bytes = bytes(key[pkcs11.Attribute.EC_POINT])
                    if len(pub_bytes) > 32:
                        pub_bytes = pub_bytes[-32:]
                    keys.append({
                        "label": label,
                        "public_key": pub_bytes.hex(),
                        "pid": hashlib.sha256(pub_bytes).hexdigest(),
                    })
                except Exception:
                    pass
        return keys

    def delete_key(self, key_label: str):
        """Delete a keypair from the HSM."""
        if not self.is_available():
            raise RuntimeError("HSM not available")

        with self._token.open(rw=True, user_pin=self._pin) as session:
            for obj_class in (ObjectClass.PRIVATE_KEY, ObjectClass.PUBLIC_KEY):
                try:
                    key = session.get_key(
                        object_class=obj_class,
                        label=key_label,
                    )
                    key.destroy()
                except Exception:
                    pass


class HSMSigner:
    """
    Duck-type compatible signer that delegates to HSM.

    Can be used anywhere an Ed25519PrivateKey is expected for signing,
    as long as the caller uses .sign(data) interface.
    """

    def __init__(self, hsm: HSMKeyStore, key_label: str):
        self._hsm = hsm
        self._key_label = key_label

    def sign(self, data: bytes) -> bytes:
        """Sign data using the HSM-stored key."""
        return self._hsm.sign(data, self._key_label)
