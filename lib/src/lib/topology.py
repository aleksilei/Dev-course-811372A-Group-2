"""The scaled docker-compose stack: extra gateway sites on top of the default one.

Usage: python -m lib.topology <out dir> <gateways> <readers per gateway> [classical]

Writes into <out dir>, for `make run-scaled`:
- docker-compose.scaled.yml: an override adding the sites to docker-compose.yml
- certs/: the dev CA and the server certificates, one per site gateway
- seed.sql: cloud/seed.sql plus the sites' gateways, readers and groups

Site n is gateway gw-s<n> with readers rd-s<n>-1.. on a reader VLAN of its own,
10.10.<n>.0/24, the gateway at 10.10.<n>.10. The last `classical` sites stand
in for gateways without ML-KEM, like gateway-2 in the default stack. Sites
take turns at the scan ranges in SITE_SCAN_INTERVALS, so some are much busier
than others.

When the topology changes, the certificates are made again and the scaled
cloud database is deleted, so the cloud seeds itself with the new sites.
"""

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from lib.certs import COMPOSE_SERVERS, generate

ROOT = Path(__file__).resolve().parents[3]
BASE_SEED = ROOT / 'cloud' / 'seed.sql'
COMPOSE_FILE = 'docker-compose.scaled.yml'
GATEWAY_PORT = 8765
MAX_GATEWAYS = 254  # 10.10.0.0/24 is the default stack's reader VLAN
MAX_READERS = 200

# Zones each site's readers get in turn, with the groups that may open them
# (the same rules as the default stack's seed.sql).
ZONES = [
    ('front-door', ['visitors', 'employees', 'sysadmins', 'executives']),
    ('employee-door', ['employees', 'sysadmins', 'executives']),
    ('server-room', ['sysadmins']),
    ('executive-room', ['executives']),
    ('loading-dock', ['employees']),
    ('lab', ['employees', 'sysadmins']),
    ('storage', ['employees']),
    ('meeting-room', ['employees', 'executives']),
]

# Seconds between a reader's scans (SCAN_INTERVAL_MIN, SCAN_INTERVAL_MAX), for
# sites 1, 2, 3, 4, 5, ...: busy, normal (the default stack's 2-8 s), quiet,
# very quiet, busy, ... On average 2, 5, 10 and 20 s.
SITE_SCAN_INTERVALS = [(1, 3), (2, 8), (5, 15), (10, 30)]


@dataclass(frozen=True)
class Topology:
    gateways: int
    readers: int  # per gateway
    classical: int = 2

    def __post_init__(self) -> None:
        if not 1 <= self.gateways <= MAX_GATEWAYS:
            raise ValueError(f'gateways must be 1..{MAX_GATEWAYS}')
        if not 1 <= self.readers <= MAX_READERS:
            raise ValueError(f'readers per gateway must be 1..{MAX_READERS}')
        if not 0 <= self.classical <= self.gateways:
            raise ValueError('classical must be 0..gateways')

    def sites(self) -> range:
        return range(1, self.gateways + 1)

    def is_classical(self, site: int) -> bool:
        return site > self.gateways - self.classical


def gateway_ip(site: int) -> str:
    return f'10.10.{site}.10'


def scan_interval(site: int) -> tuple[int, int]:
    return SITE_SCAN_INTERVALS[(site - 1) % len(SITE_SCAN_INTERVALS)]


def zone(site: int, reader: int) -> tuple[str, list[str]]:
    """The zone name and the groups that may open it, for reader `reader` of a site."""
    name, groups = ZONES[(reader - 1) % len(ZONES)]
    lap = (reader - 1) // len(ZONES)
    return f's{site}-{name}' + (f'-{lap + 1}' if lap else ''), groups


def servers(topology: Topology) -> dict[str, str]:
    """Certificates to make: the default stack's plus one per site gateway."""
    sites = {
        f'gateway-s{n}': f'IP:{gateway_ip(n)},DNS:localhost,IP:127.0.0.1'
        for n in topology.sites()
    }
    return {**COMPOSE_SERVERS, **sites}


def compose(topology: Topology) -> dict:
    """The override that adds the sites to docker-compose.yml."""
    data = '${DATA_DIR}'
    ca = f'{data}/certs/ca.pem:/certs/ca.pem:ro'
    services: dict[str, dict] = {
        # The cloud seeds itself from the scaled seed.sql instead.
        'cloud': {'volumes': [f'{data}/seed.sql:/app/cloud/seed.sql:ro']},
    }
    networks: dict[str, dict] = {}
    for n in topology.sites():
        network = f'site-{n}-vlan'
        low, high = scan_interval(n)
        networks[network] = {
            'internal': True,
            'ipam': {'config': [{'subnet': f'10.10.{n}.0/24'}]},
        }
        environment = {'CLOUD': 'cloud:8443', 'ID': f'gw-s{n}'}
        if topology.is_classical(n):
            environment['KEY_EXCHANGE'] = 'classical'
        services[f'gateway-s{n}'] = {
            'image': 'dev-course/gateway',
            'pull_policy': 'never',
            'environment': environment,
            'volumes': [
                ca,
                f'{data}/certs/gateway-s{n}.pem:/certs/server.pem:ro',
                f'{data}/certs/gateway-s{n}.key:/certs/server.key:ro',
            ],
            'networks': {network: {'ipv4_address': gateway_ip(n)}, 'wan': {}},
            'depends_on': ['cloud'],
            'restart': 'unless-stopped',
        }
        for r in range(1, topology.readers + 1):
            services[f'reader-s{n}-{r}'] = {
                'image': 'dev-course/reader',
                'pull_policy': 'never',
                'environment': {
                    'READER_ID': f'rd-s{n}-{r}',
                    'ZONE': zone(n, r)[0],
                    'GATEWAY': f'{gateway_ip(n)}:{GATEWAY_PORT}',
                    'KEYS': 'key-alice,key-bob,key-carol,key-mallory',
                    'SCAN_INTERVAL_MIN': str(low),
                    'SCAN_INTERVAL_MAX': str(high),
                },
                'volumes': [ca],
                'networks': [network],
                'depends_on': [f'gateway-s{n}'],
                'restart': 'unless-stopped',
            }
    return {'services': services, 'networks': networks}


def seed(topology: Topology, base: str) -> str:
    """The default stack's seed data plus the sites' gateways and readers."""
    gateways, readers, groups = [], [], []
    for n in topology.sites():
        gateways.append(f"('gw-s{n}')")
        for r in range(1, topology.readers + 1):
            name, allowed = zone(n, r)
            readers.append(f"('rd-s{n}-{r}', 'gw-s{n}', '{name}')")
            groups += [f"('rd-s{n}-{r}', '{group}')" for group in allowed]
    return (
        f'{base.rstrip()}\n\n'
        f'-- Scaled stack ({topology.gateways} sites x {topology.readers} '
        f'readers), written by lib.topology.\n\n'
        f'INSERT INTO GATEWAYS (id) VALUES\n    {",\n    ".join(gateways)};\n\n'
        f'INSERT INTO READERS (id, gateway_id, zone_name) VALUES\n'
        f'    {",\n    ".join(readers)};\n\n'
        f'INSERT INTO READER_GROUPS (reader_id, group_id) VALUES\n'
        f'    {",\n    ".join(groups)};\n'
    )


def write(out_dir: str | Path, topology: Topology, base_seed: Path = BASE_SEED) -> bool:
    """Write the scaled stack's files; True when the topology changed."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    marker = out / 'topology.json'
    current = json.dumps(asdict(topology))
    changed = not marker.exists() or marker.read_text(encoding='utf-8') != current
    if changed or not (out / 'certs' / 'ca.pem').exists():
        generate(out / 'certs', servers(topology))
    if changed:
        (out / 'cloud' / 'master.db').unlink(missing_ok=True)
    (out / 'cloud').mkdir(exist_ok=True)
    # JSON is valid YAML, and needs no YAML library.
    (out / COMPOSE_FILE).write_text(
        '# Written by lib.topology for `make run-scaled`: do not edit.\n'
        + json.dumps(compose(topology), indent=2)
        + '\n',
        encoding='utf-8',
    )
    (out / 'seed.sql').write_text(
        seed(topology, base_seed.read_text(encoding='utf-8')), encoding='utf-8'
    )
    marker.write_text(current, encoding='utf-8')
    return changed


if __name__ == '__main__':
    try:
        topo = Topology(*(int(arg) for arg in sys.argv[2:]))
    except (TypeError, ValueError) as error:
        sys.exit(f'{error}\n{__doc__.splitlines()[2]}')
    CHANGED = write(sys.argv[1], topo)
    print(
        f'Scaled stack in {sys.argv[1]}: {topo.gateways} gateways x {topo.readers} '
        f'readers ({topo.classical} classical)'
        + ('; new topology, so the scaled database starts fresh' if CHANGED else '')
    )
