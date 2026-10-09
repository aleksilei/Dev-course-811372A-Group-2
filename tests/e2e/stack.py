"""The docker-compose stack under test, looked at from outside: through the
control panel, the containers' logs, and probes run inside the containers."""

import http.client
import json
import os
import re
import subprocess
import time
import urllib.request
from pathlib import Path

from lib import tls

ROOT = Path(__file__).parents[2]
PROBE = Path(__file__).with_name('tls_probe.py')
# Its own project, so the tests never touch the dev stack's containers.
PROJECT = 'dev-course-e2e'
# Everything but sqlite-web.
SERVICES = ['cloud', 'gateway-1', 'gateway-2', *(f'reader-{n}' for n in range(1, 6))]
SCAN_INTERVAL = 1
PANEL = 'https://localhost:8444'
# The line reader.scanner.scan() logs for every scan.
SCAN = re.compile(r'(PASS|FAIL) key=(\S+) reader=')


def wait_for(condition, what, timeout=60.0):
    """Poll condition() until it returns something truthy, and return that.

    Connection errors count as not yet: the panel may be (re)starting.
    """
    deadline = time.monotonic() + timeout
    while True:
        try:
            result = condition()
        except (OSError, http.client.HTTPException):
            result = None
        if result:
            return result
        if time.monotonic() > deadline:
            raise AssertionError(f'timed out after {timeout:.0f} s waiting for {what}')
        time.sleep(0.25)


class Stack:
    def __init__(self, data_dir: Path) -> None:
        self.env = {'DATA_DIR': str(data_dir), 'SCAN_INTERVAL': str(SCAN_INTERVAL)}
        self.context = tls.client_context(
            str(data_dir / 'certs' / 'ca.pem'), tls.ADMIN_CLOUD
        )

    def compose(self, *args: str, files=('docker-compose.yml',), stdin=None) -> str:
        """Run `docker compose <args>` for the e2e project and return its stdout."""
        command = ['docker', 'compose', '--project-name', PROJECT]
        for file in files:
            command += ['--file', file]
        result = subprocess.run(
            [*command, *args],
            cwd=ROOT,
            env={**os.environ, **self.env},
            input=stdin,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f'{" ".join(command[2:] + list(args))}:\n{result.stderr}'
            )
        return result.stdout

    def up(self, *services: str, files=('docker-compose.yml',)) -> None:
        """Start (or recreate, if their config changed) services from the built images."""
        options = ['--detach', '--no-build', '--pull', 'never', '--timeout', '1']
        self.compose('up', *options, *services, files=files)

    def api(self, path: str, body: dict | None = None):
        """GET the control panel's /api/<path>, or POST a JSON body to it."""
        request = urllib.request.Request(
            f'{PANEL}/api/{path}',
            data=None if body is None else json.dumps(body).encode(),
            headers={'Content-Type': 'application/json'},
        )
        with urllib.request.urlopen(request, context=self.context, timeout=5) as reply:
            data = reply.read()
        return json.loads(data) if data else None

    def gateways(self) -> dict[str, str]:
        """{gateway ID: key exchange} of the gateways connected to the cloud."""
        return {
            gateway['id']: gateway['key_exchange'] for gateway in self.api('gateways')
        }

    def wait_until_connected(self) -> None:
        wait_for(
            lambda: set(self.gateways()) == {'gw-1', 'gw-2'},
            'both gateways to connect to the cloud',
        )

    def logs(self, service: str) -> list[str]:
        return self.compose(
            'logs', '--no-color', '--no-log-prefix', service
        ).splitlines()

    def mark(self, service: str) -> int:
        """A position in the service's log, for logs(service)[mark:] and scans()."""
        return len(self.logs(service))

    def scans(self, reader_service: str, since: int = 0) -> list[tuple[str, str]]:
        """(PASS or FAIL, key) for every scan the reader logged after `since`."""
        lines = self.logs(reader_service)[since:]
        return [match.groups() for line in lines if (match := SCAN.search(line))]

    def probe(self, service: str, server: str) -> str:
        """The key-exchange group a TLS client in `service` negotiates with
        `server` (host:port), offering whatever that container's OpenSSL offers."""
        host, port = server.rsplit(':', 1)
        output = self.compose(
            'exec',
            '-T',
            service,
            'python',
            '-',
            host,
            port,
            stdin=PROBE.read_text(encoding='utf-8'),
        )
        return output.strip()
