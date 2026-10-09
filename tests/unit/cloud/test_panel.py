import http.client
import json
import threading
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest

from cloud.gateways import GatewayHub
from cloud.panel import MAX_BODY, PanelServer
from lib import tls

# A POST body the panel accepts, granting key-mallory the front door (rd-1).
GRANT = {'key': 'key-mallory', 'group': 'visitors', 'member': True}


@pytest.fixture(name='panel')
def panel_fixture(certs, db):
    """A running panel: `host` (localhost:<port>) and a client TLS context."""
    server = PanelServer(
        ('127.0.0.1', 0),
        tls.server_context(certs.cert, certs.key, tls.ADMIN_CLOUD),
        db,
        GatewayHub(db),
    )
    threading.Thread(
        target=server.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True
    ).start()
    yield SimpleNamespace(
        host=f'localhost:{server.server_address[1]}',
        context=tls.client_context(certs.ca, tls.ADMIN_CLOUD),
    )
    server.shutdown()
    server.server_close()


@pytest.fixture(name='get')
def get_fixture(panel):
    """GET a path from the panel: returns (status, content type, body)."""

    def fetch(path):
        url = f'https://{panel.host}{path}'
        try:
            with urllib.request.urlopen(url, context=panel.context) as response:
                return (
                    response.status,
                    response.headers['Content-Type'],
                    response.read(),
                )
        except urllib.error.HTTPError as error:
            return error.code, error.headers['Content-Type'], error.read()

    return fetch


@pytest.fixture(name='post')
def post_fixture(panel):
    """POST to the panel, sending exactly the given headers: returns (status, body).

    The body is JSON-encoded unless it is bytes. Content-Type and
    Content-Length are set as the control panel's fetch() sets them; `headers`
    adds to or overrides them, and a None value leaves a header out.
    """

    def send(path, body, headers=None):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        sent = {
            'Content-Type': 'application/json',
            'Content-Length': str(len(data)),
            **(headers or {}),
        }
        conn = http.client.HTTPSConnection(panel.host, context=panel.context)
        try:
            conn.putrequest('POST', path, skip_accept_encoding=True)
            for name, value in sent.items():
                if value is not None:
                    conn.putheader(name, value)
            conn.endheaders(data)
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    return send


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


def test_access_api(get, db):
    status, content_type, body = get('/api/access')

    assert (status, content_type) == (200, 'application/json')
    assert json.loads(body) == db.access()


def test_adding_a_key_to_a_group_grants_access(post, db):
    assert post('/api/key-groups', GRANT) == (204, b'')

    assert db.authorize('key-mallory', 'rd-1', 'gw-1') == 'pass'


def test_removing_a_key_from_a_group_revokes_access(post, db):
    body = {'key': 'key-bob', 'group': 'sysadmins', 'member': False}

    assert post('/api/key-groups', body) == (204, b'')

    assert db.authorize('key-bob', 'rd-3', 'gw-1') == 'fail'


def test_reader_groups_can_be_changed(post, db):
    body = {'reader': 'rd-3', 'group': 'employees', 'member': True}

    assert post('/api/reader-groups', body) == (204, b'')
    assert db.authorize('key-alice', 'rd-3', 'gw-1') == 'pass'

    assert post('/api/reader-groups', {**body, 'member': False}) == (204, b'')
    assert db.authorize('key-alice', 'rd-3', 'gw-1') == 'fail'


def test_member_id_is_stripped(post, db):
    post('/api/key-groups', {**GRANT, 'key': '  key-mallory\n'})

    assert db.access()['keys'] == ['key-alice', 'key-bob', 'key-carol', 'key-mallory']


@pytest.mark.parametrize(
    ('path', 'body', 'message'),
    [
        ('/api/key-groups', {**GRANT, 'group': 'nope'}, b"unknown group 'nope'"),
        (
            '/api/reader-groups',
            {'reader': 'rd-9', 'group': 'visitors', 'member': True},
            b"unknown reader 'rd-9'",
        ),
        ('/api/nope', GRANT, b'Not found'),
        ('/api/access', GRANT, b'Not found'),
    ],
)
def test_unknown_targets_are_not_found(post, path, body, message):
    assert post(path, body) == (404, message)


@pytest.mark.parametrize(
    'body',
    [
        b'not json',
        b'["key-mallory", "visitors", true]',
        {'group': 'visitors', 'member': True},
        {**GRANT, 'key': '   '},
        {**GRANT, 'key': 42},
        {**GRANT, 'group': None},
        {**GRANT, 'member': 'true'},
        {**GRANT, 'member': 1},
        {'reader': 'rd-1', 'group': 'visitors', 'member': True},  # wrong endpoint
    ],
)
def test_malformed_bodies_are_rejected(post, db, body):
    before = db.access()

    assert post('/api/key-groups', body)[0] == 400

    assert db.access() == before


def test_requests_from_the_panel_and_without_origin_are_allowed(panel, post, db):
    # Browsers send Origin with every POST; curl and scripts send none.
    assert post('/api/key-groups', GRANT, {'Origin': f'https://{panel.host}'})[0] == 204
    assert post('/api/key-groups', {**GRANT, 'member': False})[0] == 204
    assert post(
        '/api/key-groups', GRANT, {'Content-Type': 'application/json; charset=utf-8'}
    ) == (204, b'')
    assert db.authorize('key-mallory', 'rd-1', 'gw-1') == 'pass'


@pytest.mark.parametrize(
    ('headers', 'status'),
    [
        # Another web page open in the admin's browser (CSRF):
        ({'Origin': 'https://evil.example'}, 403),
        ({'Origin': 'https://{host}.evil.example'}, 403),
        ({'Origin': 'http://{host}'}, 403),
        ({'Origin': 'null'}, 403),  # sandboxed iframes, file:// pages
        # The content types a cross-site form or no-cors fetch can send:
        ({'Content-Type': 'text/plain'}, 415),
        ({'Content-Type': 'application/x-www-form-urlencoded'}, 415),
        ({'Content-Type': 'multipart/form-data; boundary=x'}, 415),
        ({'Content-Type': None}, 415),
        # Bodies the panel won't read:
        ({'Content-Length': None}, 411),
        ({'Content-Length': 'lots'}, 411),
        ({'Content-Length': str(MAX_BODY + 1)}, 413),
        ({'Content-Length': '-1'}, 413),
    ],
)
def test_refused_requests_change_nothing(panel, post, db, headers, status):
    headers = {
        name: value and value.format(host=panel.host) for name, value in headers.items()
    }

    assert post('/api/key-groups', GRANT, headers)[0] == status

    assert db.authorize('key-mallory', 'rd-1', 'gw-1') == 'fail'
