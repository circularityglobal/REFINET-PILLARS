# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.3.x   | Yes       |
| 0.2.x   | Yes       |
| 0.1.x   | No        |

## Reporting a Vulnerability

Do NOT open a public GitHub issue for security vulnerabilities.

Report privately via:
- **GitHub Security Advisories** (preferred)
- **Email:** security@refinet.network

### Response Timeline
- **Acknowledgment:** 48 hours
- **Critical patch:** 7 days
- **Moderate patch:** 30 days

## Cryptographic Primitives

| Primitive | Usage |
|-----------|-------|
| Ed25519 | Pillar identity (PID) keypair, content signing |
| AES-256-GCM | Encrypted vault storage |
| Argon2id | Key derivation for encrypted key storage |
| X25519 | Key exchange for encrypted channels |
| Shamir SSS (GF256/0x11D) | Key recovery (k-of-n threshold shares) |
| Schnorr ZKP (Fiat-Shamir) | Zero-knowledge proof of key ownership |
| SIWE (EIP-4361) | Wallet-based authentication |

## Security Architecture

- Private keys never leave the local machine
- WebSocket CORS restricted to configured origin allowlist
- SSRF protection on proxy (RFC 1918 + loopback blocked)
- Rate limiting: 100 requests / 60 seconds per IP
- Path traversal protection on all file-serving routes
- Content signing with Ed25519 on every served response
- Systemd hardening: NoNewPrivileges, ProtectSystem=strict, ProtectHome=read-only

## Scope

The following are in scope for security reports:
- Authentication bypass (SIWE, session tokens)
- Cryptographic implementation flaws
- Path traversal or file disclosure
- Remote code execution
- Denial of service (resource exhaustion)
- WebSocket or proxy abuse
- Cross-origin attacks via the browser extension
