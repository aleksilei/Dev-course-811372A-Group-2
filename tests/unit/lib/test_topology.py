import json
import os
import shutil
import subprocess

import pytest

from cloud import db as cloud_db
from lib import topology
from lib.topology import COMPOSE_FILE, ROOT, Topology, compose, servers, write

SMALL = Topology(gateways=3, readers=10, classical=1)


def test_every_site_gets_a_gateway_and_its_readers_on_their_own_vlan():
    services = compose(SMALL)['services']

    gateway = services['gateway-s2']
    assert gateway['environment']['ID'] == 'gw-s2'
    assert gateway['networks']['site-2-vlan'] == {'ipv4_address': '10.10.2.10'}
    reader = services['reader-s2-10']
    assert reader['environment']['READER_ID'] == 'rd-s2-10'
    assert reader['environment']['GATEWAY'] == '10.10.2.10:8765'
    assert reader['networks'] == ['site-2-vlan']
    readers = [name for name in services if name.startswith('reader-')]
    assert len(readers) == SMALL.gateways * SMALL.readers


def test_the_last_sites_are_classical():
    services = compose(SMALL)['services']

    assert 'KEY_EXCHANGE' not in services['gateway-s2']['environment']
    assert services['gateway-s3']['environment']['KEY_EXCHANGE'] == 'classical'


def test_zones_repeat_with_a_number_after_a_lap():
    services = compose(SMALL)['services']

    assert services['reader-s1-1']['environment']['ZONE'] == 's1-front-door'
    assert services['reader-s1-9']['environment']['ZONE'] == 's1-front-door-2'


def test_every_site_gateway_gets_a_certificate_for_its_ip():
    certs = servers(SMALL)

    assert 'IP:10.10.3.10' in certs['gateway-s3']
    assert certs['gateway'] == topology.COMPOSE_SERVERS['gateway']


@pytest.mark.parametrize(
    'args', [(0, 8), (255, 8), (10, 0), (10, 201), (2, 8, 3), (2, 8, -1)]
)
def test_out_of_range_topologies_are_refused(args):
    with pytest.raises(ValueError):
        Topology(*args)


@pytest.fixture(name='scaled_db')
def scaled_db_fixture(tmp_path, monkeypatch):
    """A cloud database seeded from the generated seed.sql."""
    seed = tmp_path / 'seed.sql'
    seed.write_text(
        topology.seed(SMALL, topology.BASE_SEED.read_text(encoding='utf-8')),
        encoding='utf-8',
    )
    monkeypatch.setattr(cloud_db, 'SEED', seed)
    database = cloud_db.Database(tmp_path / 'master.db')
    database.init()
    return database


@pytest.mark.parametrize(
    ('key', 'reader', 'expected'),
    [
        ('key-alice', 'rd-1', 'pass'),  # the default stack is still there
        ('key-mallory', 'rd-s1-1', 'fail'),
        ('key-alice', 'rd-s2-1', 'pass'),  # front door
        ('key-alice', 'rd-s2-3', 'fail'),  # server room
        ('key-bob', 'rd-s2-3', 'pass'),
        ('key-carol', 'rd-s3-4', 'pass'),  # executive room
        ('key-alice', 'rd-s3-4', 'fail'),
    ],
)
def test_the_seed_gives_site_readers_the_default_access_rules(
    scaled_db, key, reader, expected
):
    assert scaled_db.authorize(key, reader, 'gw-s1') == expected


def test_the_seed_holds_every_reader(scaled_db):
    readers = {r['id']: r for r in scaled_db.readers()}

    assert len(readers) == 5 + SMALL.gateways * SMALL.readers
    assert readers['rd-s3-10']['gateway_id'] == 'gw-s3'


def test_a_new_topology_resets_the_database_and_the_same_one_keeps_it(
    tmp_path, monkeypatch
):
    made = []
    monkeypatch.setattr(topology, 'generate', lambda out, names: made.append(names))
    database = tmp_path / 'cloud' / 'master.db'

    assert write(tmp_path, SMALL)
    database.write_text('edited in the panel', encoding='utf-8')
    (tmp_path / 'certs').mkdir()
    (tmp_path / 'certs' / 'ca.pem').touch()

    assert not write(tmp_path, SMALL)
    assert database.exists()
    assert len(made) == 1

    assert write(tmp_path, Topology(gateways=4, readers=10))
    assert not database.exists()
    assert len(made) == 2
    _comment, body = (
        (tmp_path / COMPOSE_FILE).read_text(encoding='utf-8').split('\n', 1)
    )
    assert 'gateway-s4' in json.loads(body)['services']


@pytest.mark.skipif(shutil.which('docker') is None, reason='needs docker compose')
def test_docker_compose_accepts_the_override(tmp_path, monkeypatch):
    monkeypatch.setattr(topology, 'generate', lambda out, names: None)
    write(tmp_path, SMALL)

    result = subprocess.run(
        [
            'docker',
            'compose',
            '--project-name',
            'topology-test',
            '-f',
            'docker-compose.yml',
            '-f',
            str(tmp_path / COMPOSE_FILE),
            'config',
            '--services',
        ],
        cwd=ROOT,
        env={**os.environ, 'DATA_DIR': str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    services = result.stdout.split()
    # The default stack's 9 services, then a gateway and its readers per site.
    assert len(services) == 9 + SMALL.gateways * (1 + SMALL.readers)
