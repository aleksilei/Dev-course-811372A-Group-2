"""Dev CA and server certificates, generated with the OpenSSL 3 command line tool.

Usage: python -m lib.certs <output dir>
"""

import subprocess
import sys
import tempfile
from pathlib import Path

# Server certificates for the docker-compose deployment: name -> subjectAltName.
# localhost is included so the servers can also be reached from the host.
COMPOSE_SERVERS = {
    'gateway': 'IP:10.10.0.10,DNS:localhost,IP:127.0.0.1',
    'gateway-2': 'IP:10.10.0.11,DNS:localhost,IP:127.0.0.1',
    'cloud': 'DNS:cloud,DNS:localhost,IP:127.0.0.1',
}

CA_EXTENSIONS = """
basicConstraints = critical, CA:TRUE
keyUsage = critical, keyCertSign, cRLSign
subjectKeyIdentifier = hash
"""

SERVER_EXTENSIONS = """
basicConstraints = critical, CA:FALSE
keyUsage = critical, digitalSignature
extendedKeyUsage = serverAuth
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid
subjectAltName = {san}
"""


def generate(out_dir: str | Path, servers: dict[str, str]) -> None:
    """Write ca.pem/ca.key and <name>.pem/<name>.key for every server."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    _create(out / 'ca', 'Dev CA', CA_EXTENSIONS)
    for name, san in servers.items():
        _create(
            out / name,
            name,
            SERVER_EXTENSIONS.format(san=san),
            '-CA',
            str(out / 'ca.pem'),
            '-CAkey',
            str(out / 'ca.key'),
        )


def _create(path: Path, common_name: str, extensions: str, *args: str) -> None:
    # A minimal config keeps the output independent of the system openssl.cnf.
    config = f'[req]\ndistinguished_name = dn\n[dn]\n[ext]\n{extensions}'
    with tempfile.NamedTemporaryFile('w', suffix='.cnf') as config_file:
        config_file.write(config)
        config_file.flush()
        command = ['openssl', 'req', '-x509', '-noenc', '-days', '365']
        command += ['-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:P-256']
        command += ['-config', config_file.name, '-extensions', 'ext']
        command += ['-subj', f'/CN={common_name}']
        command += ['-keyout', f'{path}.key', '-out', f'{path}.pem', *args]
        subprocess.run(command, check=True, capture_output=True)


if __name__ == '__main__':
    generate(sys.argv[1], COMPOSE_SERVERS)
    print(f'Certificates written to {sys.argv[1]}')
