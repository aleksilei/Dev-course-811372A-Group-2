import os
from pathlib import Path

import pytest

from lib.certs import COMPOSE_SERVERS, generate
from tests.e2e.stack import SERVICES, Stack


@pytest.fixture(scope='session')
def stack(tmp_path_factory):
    """The compose stack, started from the built images with fresh certificates
    and a fresh database (the example data), in a data dir of its own.

    Set E2E_LOGS to a file path to keep the containers' logs.
    """
    data_dir = tmp_path_factory.mktemp('data')
    generate(data_dir / 'certs', COMPOSE_SERVERS)
    (data_dir / 'cloud').mkdir()
    running = Stack(data_dir)
    try:
        try:
            running.up(*SERVICES)
        except RuntimeError as error:
            pytest.fail(
                f'{error}\nBuild the images first (make build), and stop the dev '
                'stack (make stop): both use the same ports and reader VLAN subnet.'
            )
        running.wait_until_connected()
        yield running
    finally:
        if log_file := os.environ.get('E2E_LOGS'):
            logs = running.compose('logs', '--no-color', '--timestamps')
            Path(log_file).write_text(logs, encoding='utf-8')
        running.compose('down', '--timeout', '1')
