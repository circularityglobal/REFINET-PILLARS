# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for REFInet Pillar — Windows .exe build.

Usage:
    pyinstaller build/refinet-pillar.spec

Produces: dist/refinet-pillar-setup.exe (single-file executable)
"""

import os
import sys
from pathlib import Path

block_cipher = None

PROJECT_ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))

# ---------------------------------------------------------------------------
# Collect all gopherroot data files  (dest: gopherroot/)
# ---------------------------------------------------------------------------
gopherroot_dir = os.path.join(PROJECT_ROOT, 'gopherroot')
gopherroot_datas = []
for dirpath, dirnames, filenames in os.walk(gopherroot_dir):
    for fname in filenames:
        src = os.path.join(dirpath, fname)
        # Preserve relative path under gopherroot/
        rel = os.path.relpath(dirpath, PROJECT_ROOT)
        gopherroot_datas.append((src, rel))

# ---------------------------------------------------------------------------
# Hidden imports — modules loaded dynamically or behind try/except
# ---------------------------------------------------------------------------
hidden_imports = [
    # Core packages
    'core', 'core.config', 'core.dapp', 'core.gopher_client',
    'core.gopher_server', 'core.gopherhole', 'core.gophermap_parser',
    'core.menu_builder', 'core.readiness', 'core.tor_manager',
    'core.vpn_manager', 'core.watchdog',
    # Crypto
    'crypto', 'crypto.binding', 'crypto.hsm', 'crypto.pid',
    'crypto.profiles', 'crypto.recovery', 'crypto.signing',
    'crypto.tls', 'crypto.zkp',
    # DB
    'db', 'db.archive_db', 'db.audit', 'db.live_db', 'db.schema',
    # Auth
    'auth', 'auth.session', 'auth.siwe',
    # Mesh
    'mesh', 'mesh.discovery', 'mesh.encrypted_channel', 'mesh.replication',
    # RPC
    'rpc', 'rpc.chains', 'rpc.config', 'rpc.gateway',
    # CLI subcommands
    'cli', 'cli.hole', 'cli.peer',
    # Proxy
    'proxy', 'proxy.forward_proxy',
    # Integration
    'integration', 'integration.ipc_socket', 'integration.websocket_bridge',
    # Vault
    'vault', 'vault.storage',
    # Onboarding
    'onboarding', 'onboarding.server', 'onboarding.readiness_step',
    'onboarding.wizard',
    # stdlib that PyInstaller sometimes misses
    'sqlite3', 'asyncio', 'json', 'hashlib', 'hmac',
    # Required C-extension backends
    'cryptography', 'cryptography.hazmat', 'cryptography.hazmat.primitives',
    'cryptography.hazmat.primitives.asymmetric',
    'cryptography.hazmat.primitives.asymmetric.ed25519',
    'cryptography.hazmat.primitives.ciphers',
    'cryptography.hazmat.primitives.kdf',
    'cryptography.hazmat.primitives.serialization',
    'cryptography.hazmat.backends',
    'cryptography.hazmat.backends.openssl',
    'cryptography.x509',
    'argon2', 'argon2.low_level',
    '_argon2_cffi_bindings',
]

# Optional dependencies — include if installed, skip gracefully if not
optional_imports = [
    'eth_account', 'eth_account.account', 'eth_account.signers',
    'web3', 'web3.auto',
    'websockets', 'websockets.server', 'websockets.legacy',
    'websockets.legacy.server',
    'stem', 'stem.control',
    'qrcode', 'PIL',
]

for mod in optional_imports:
    try:
        __import__(mod.split('.')[0])
        hidden_imports.append(mod)
    except ImportError:
        pass

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
a = Analysis(
    [os.path.join(PROJECT_ROOT, 'pillar.py')],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=gopherroot_datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tests', 'pytest', 'pytest_asyncio', '_pytest',
        'tkinter', 'matplotlib', 'numpy', 'scipy',
        'IPython', 'notebook', 'jupyter',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# ---------------------------------------------------------------------------
# Bundle
# ---------------------------------------------------------------------------
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='refinet-pillar-setup',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,          # CLI daemon — needs console
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,             # TODO: add icon when available
)
