# REFInet Pillar Documentation

Welcome to the REFInet Pillar documentation. REFInet Pillar is a sovereign Gopher mesh node — your own cryptographically-signed identity in a decentralized network.

## Quick Links

- **[Getting Started](GETTING-STARTED.md)** — Install and run your first Pillar
- **[Platform Overview](PLATFORM_OVERVIEW.md)** — Architecture and component deep dive
- **[Developer Guide](DEV_GUIDE.md)** — Module reference, API docs, testing
- **[Whitepaper](WHITEPAPER.md)** — Full protocol specification

## Install

```bash
pip3 install refinet-pillar[full]
refinet-pillar run
```

Or with Docker:

```bash
docker run -d -p 7070:7070 -p 7075:7075 \
  -v ~/.refinet:/home/refinet/.refinet \
  refinet/pillar:latest
```

## Resources

- [Security Policy](SECURITY.md)
- [Changelog](CHANGELOG.md)
- [GitHub Repository](https://github.com/refinet/pillar)
- Gopherspace: `gopher://pillar.refinet.network:7070`
