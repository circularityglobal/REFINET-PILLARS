FROM python:3.11-slim

LABEL org.opencontainers.image.title="REFInet Pillar"
LABEL org.opencontainers.image.description="Sovereign Gopher mesh node with Ed25519 identity"
LABEL org.opencontainers.image.version="0.2.0"
LABEL org.opencontainers.image.source="https://github.com/refinet/pillar"
LABEL org.opencontainers.image.licenses="AGPL-3.0-or-later"

# Create dedicated user
RUN groupadd -r refinet && useradd -r -g refinet -m -d /home/refinet refinet

WORKDIR /opt/refinet

# Install dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .
RUN chown -R refinet:refinet /opt/refinet

USER refinet

# Data persists in /home/refinet/.refinet via volume
VOLUME ["/home/refinet/.refinet"]

# REFInet (7070), Gopher (70), GopherS (7073), Proxy (7074), WebSocket (7075)
EXPOSE 7070 70 7073 7074 7075

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import socket; s=socket.socket(); s.settimeout(3); s.connect(('127.0.0.1',7070)); s.send(b'/health\r\n'); d=s.recv(1024); s.close(); exit(0 if d else 1)"

ENTRYPOINT ["python3", "pillar.py"]
CMD ["run", "--host", "0.0.0.0"]
