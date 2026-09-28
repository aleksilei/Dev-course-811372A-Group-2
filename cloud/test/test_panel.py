import json
import threading
import urllib.error
import urllib.request

import pytest

from cloud.gateways import GatewayHub
from cloud.panel import PanelServer
from lib import tls


@pytest.fixture
def get(certs, db):
    """GET a path from a running panel: returns (status, content type, body)."""
    server = PanelServer(
        ('127.0.0.1', 0),
        tls.server_context(certs.cert, certs.key, tls.ADMIN_CLOUD),
        db,
        GatewayHub(db),
    )
    threading.Thread(
        target=server.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True
    ).start()
    base_url = f'https://localhost:{server.server_address[1]}'
    context = tls.client_context(certs.ca, tls.ADMIN_CLOUD)

    def fetch(path):
        try:
            with urllib.request.urlopen(base_url + path, context=context) as response:
                return (
                    response.status,
                    response.headers['Content-Type'],
                    response.read(),
                )
        except urllib.error.HTTPError as error:
            return error.code, error.headers['Content-Type'], error.read()

    yield fetch
    server.shutdown()
    server.server_close()


@pytest.mark.parametrize(
    ('path', 'content_type'),
    [('/', 'text/html'), ('/app.js', 'text/javascript'), ('/style.css', 'text/css')],
)
def test_serves_the_static_panel(get, path, content_type):
    status, received_type, body = get(path)

    assert status == 200
    assert received_type.startswith(content_type)
    assert body


@pytest.mark.parametrize(
    'path', ['/nope', '/schema.sql', '/../db.py', '/static/app.js']
)
def test_unknown_paths_are_not_found(get, path):
    assert get(path)[0] == 404


def test_events_api_supports_filters(get, db):
    db.authorize('key-alice', 'rd-1', 'gw-1')
    db.authorize('key-bob', 'rd-3', 'gw-1')

    status, content_type, body = get('/api/events?key=key-bob')

    assert (status, content_type) == (200, 'application/json')
    assert [e['reader_id'] for e in json.loads(body)] == ['rd-3']
    assert len(json.loads(get('/api/events')[2])) == 2


def test_readers_api(get):
    readers = json.loads(get('/api/readers')[2])

    assert {r['id']: r['zone_name'] for r in readers}['rd-3'] == 'server-room'


def test_gateways_api_is_empty_without_connections(get):
    assert json.loads(get('/api/gateways')[2]) == []
