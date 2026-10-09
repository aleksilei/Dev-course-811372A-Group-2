# Build context: repository root (see docker-compose.yml)
FROM python:3.13-slim

COPY lib /opt/lib
RUN pip install --no-cache-dir /opt/lib

# Key exchange with gateways: hybrid X25519MLKEM768 with X25519 fallback.
# Override with hybrid-only.cnf or classical.cnf (see lib/README.md).
ENV OPENSSL_CONF=/opt/lib/openssl/hybrid.cnf

WORKDIR /app
COPY cloud ./cloud

EXPOSE 8443 8444
CMD ["python", "-m", "cloud"]
