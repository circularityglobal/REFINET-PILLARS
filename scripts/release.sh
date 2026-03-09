#!/usr/bin/env bash
set -euo pipefail

VERSION=$(python3 -c "
import tomllib
with open('pyproject.toml','rb') as f:
    d = tomllib.load(f)
print(d['project']['version'])
")

TARBALL="refinet-pillar-v${VERSION}.tar.gz"

echo "Creating release tarball for v${VERSION}..."
git archive --format=tar.gz \
    --prefix="refinet-pillar-v${VERSION}/" \
    HEAD \
    > "${TARBALL}"

sha256sum "${TARBALL}" > CHECKSUMS.txt
echo "SHA-256: $(cat CHECKSUMS.txt)"

echo ""
echo "To publish:"
echo "  git tag v${VERSION}"
echo "  git push origin v${VERSION}"
echo "  gh release create v${VERSION} ${TARBALL} CHECKSUMS.txt \\"
echo "    --title 'REFInet Pillar v${VERSION}' \\"
echo "    --notes 'See CHANGELOG.md for details'"
