#!/bin/sh
# The Dockerfiles' openssl stage (SCRUM-55): with OPENSSL_VERSION and
# OPENSSL_SHA256 set, downloads that OpenSSL release, checks it, and builds its
# shared libraries into /opt/openssl/lib. Without OPENSSL_VERSION it leaves
# /opt/openssl/lib empty, and the image keeps the base image's OpenSSL.
set -eu

mkdir -p /opt/openssl/lib
[ -n "${OPENSSL_VERSION:-}" ] || exit 0
: "${OPENSSL_SHA256:?OPENSSL_SHA256 must be set with OPENSSL_VERSION (see openssl.env)}"

apt-get update
apt-get install --yes --no-install-recommends build-essential ca-certificates curl perl

name="openssl-$OPENSSL_VERSION"
cd /tmp
curl --fail --silent --show-error --location --remote-name \
    "https://github.com/openssl/openssl/releases/download/$name/$name.tar.gz"
echo "$OPENSSL_SHA256  $name.tar.gz" | sha256sum --check -
tar -xzf "$name.tar.gz"
cd "$name"

# Built for where it ends up (/opt/openssl/lib, also the providers' directory),
# but with Debian's configuration directory, so it uses the base image's CA
# certificates and openssl.cnf.
./Configure --prefix=/opt/openssl --libdir=lib --openssldir=/etc/ssl \
    shared no-tests no-docs
make -j"$(nproc)"
make install_sw

# Keep only what Python's ssl module loads at run time.
cd /opt/openssl
find . -mindepth 1 -maxdepth 1 ! -name lib -exec rm -rf {} +
find lib -mindepth 1 -maxdepth 1 \
    ! -name libssl.so.3 ! -name libcrypto.so.3 ! -name ossl-modules \
    -exec rm -rf {} +
