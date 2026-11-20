# Build context: repository root (see docker-compose.yml)

# With OPENSSL_VERSION and OPENSSL_SHA256 (see openssl.env), this builds the
# -openssl<version> image, which uses that OpenSSL instead of the base image's
# (SCRUM-55). Without them, the image keeps the base image's OpenSSL.
FROM python:3.15-slim AS openssl
ARG OPENSSL_VERSION=
ARG OPENSSL_SHA256=
COPY docker/build-openssl.sh /usr/local/bin/
RUN build-openssl.sh

FROM python:3.15-slim

# Python's ssl module links libssl.so.3 dynamically: if there is a built one,
# the dynamic linker finds it first.
COPY --from=openssl /opt/openssl /opt/openssl
RUN if [ -e /opt/openssl/lib/libssl.so.3 ]; then \
        echo /opt/openssl/lib > /etc/ld.so.conf.d/00-openssl.conf && ldconfig; \
    fi

COPY lib /opt/lib
RUN pip install --no-cache-dir /opt/lib

WORKDIR /app
COPY cloud ./cloud

EXPOSE 8443 8444
CMD ["python", "-m", "cloud"]
