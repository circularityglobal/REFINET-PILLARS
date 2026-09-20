FROM python:3.11-slim

LABEL org.opencontainers.image.title="REFInet Pillar"
LABEL org.opencontainers.image.description="Sovereign Gopher mesh node with Ed25519 identity"
LABEL org.opencontainers.image.version="0.6.0"
LABEL org.opencontainers.image.source="https://github.com/circularityglobal/REFINET-PILLARS"
LABEL org.opencontainers.image.licenses="AGPL-3.0-or-later"

# Create dedicated user. uid/gid 999 is what -r assigned on this base image
# already; pinning it keeps volume ownership stable and lets Kubernetes
# set fsGroup: 999.
RUN groupadd -r -g 999 refinet && useradd -r -u 999 -g refinet -m -d /home/refinet refinet

WORKDIR /opt/refinet

# Install dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .
RUN chown -R refinet:refinet /opt/refinet \
    && mkdir -p /home/refinet/.refinet \
    && chown refinet:refinet /home/refinet/.refinet

# The entrypoint starts as root only to hand a root-owned volume (Fly, bind
# mounts) to refinet, then drops to refinet before any Pillar code runs.
# Platforms that start the container unprivileged (Kubernetes runAsUser: 999)
# skip that step. See scripts/headless_start.py _drop_privileges().
ENV REFINET_RUN_AS=refinet

# Data persists in /home/refinet/.refinet via volume
VOLUME ["/home/refinet/.refinet"]

# 7070 Gopher; 7073 GopherS; 7075 browser bridge and 7080 HTTP gateway
# (both loopback unless REFINET_WEBSOCKET_HOST / REFINET_HTTP_GATEWAY_HOST say otherwise)
EXPOSE 7070 7073 7075 7080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import socket; s=socket.socket(); s.settimeout(3); s.connect(('127.0.0.1',7070)); s.send(b'/health\r\n'); d=s.recv(1024); s.close(); exit(0 if d else 1)"

ENTRYPOINT ["python3", "scripts/headless_start.py"]
