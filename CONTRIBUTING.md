# Contributing to REFInet Pillar

Thank you for your interest in REFInet. Every contribution strengthens the mesh.

## Ways to Contribute

### Run a Pillar
The most valuable contribution is running your own node. Every Pillar strengthens the network.

```bash
pip3 install refinet-pillar[full]
refinet-pillar run
```

### Report Bugs
Open an issue on [GitHub](https://github.com/circularityglobal/REFINET-PILLARS/issues) using the bug report template. Include:
- Pillar version (`python3 pillar.py --status`)
- OS and Python version
- Steps to reproduce
- Expected vs actual behavior
- Logs (`python3 pillar.py run -v`)

### Submit Code
1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Make your changes
4. Run the test suite: `python -m pytest tests/ -q`
5. Submit a pull request

### Write DApps
Create `.dapp` definition files in `gopherroot/dapps/` to expose on-chain interactions through Gopher menus. See [DEV_GUIDE.md](DEV_GUIDE.md) for the DApp definition format.

### Improve Documentation
- Markdown docs live in the repo root and `docs/`
- Gopher-served docs live in `gopherroot/holes/refinet/docs/` (plain text, <72 columns)
- Website lives in `website/`

---

## Development Setup

```bash
git clone https://github.com/circularityglobal/REFINET-PILLARS.git
cd REFINET-PILLARS
pip3 install -r requirements.txt
python -m pytest tests/ -q    # Should pass 479+ tests
python3 pillar.py run -v      # Start locally with verbose logging
```

### Requirements
- Python 3.9+ (3.11+ recommended)
- All required dependencies are in `requirements.txt`
- Do **not** add new Python dependencies without discussion

---

## Code Style

- **Python 3.9+** — use `from __future__ import annotations` for forward refs
- **Type hints** on public function signatures
- **Focused functions** — each function does one thing
- **Async where needed** — the server is single-process async (`asyncio`)
- **No new dependencies** — `requirements.txt` covers everything needed
- **Tests required** — new features need tests in `tests/`

---

## Commit Messages

Use conventional-style messages:

```
feat: add peer health dashboard
fix: handle empty gophermap gracefully
docs: update getting started guide
chore: bump version to 0.3.0
test: add mesh replication edge cases
```

---

## Testing

```bash
# Run full suite
python -m pytest tests/ -q

# Run specific test file
python -m pytest tests/test_gopher_server.py -v

# Run with coverage
python -m pytest tests/ --cov=. --cov-report=term-missing
```

All PRs must pass the full test suite. Tests use `pytest` with `asyncio_mode = auto`.

---

## What Not to Do

- Do not modify `db/schema.py` immutability triggers
- Do not commit secrets, keys, or `pid.json` files
- Do not add Tor as a hard dependency (it's optional)
- Do not break backward compatibility with existing `pid_bindings` data

---

## Security Vulnerabilities

Do **not** open a public issue. See [SECURITY.md](SECURITY.md) for responsible disclosure instructions.

---

## Code of Conduct

All participants are expected to follow our [Code of Conduct](CODE_OF_CONDUCT.md).

---

## License

By contributing, you agree that your contributions will be licensed under the [AGPLv3](LICENSE).
