import json
import logging
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from cloud.db import Database
from cloud.gateways import GatewayHub

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).with_name('static')
STATIC_FILES = {
    '/': ('index.html', 'text/html; charset=utf-8'),
    '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
    '/style.css': ('style.css', 'text/css; charset=utf-8'),
}
# POST path -> (field naming the member, Database setter)
MEMBERSHIPS = {
    '/api/key-groups': ('key', 'set_key_group'),
    '/api/reader-groups': ('reader', 'set_reader_group'),
}
MAX_BODY = 4096


class BadRequest(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class PanelServer(ThreadingHTTPServer):
    """Admin control panel over HTTPS (no authentication, see README)."""

    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        context: ssl.SSLContext,
        db: Database,
        gateways: GatewayHub,
    ) -> None:
        super().__init__(address, PanelHandler)
        # The TLS handshake runs on first read, inside the per-request thread.
        self.socket = context.wrap_socket(
            self.socket, server_side=True, do_handshake_on_connect=False
        )
        self.db = db
        self.gateways = gateways


class PanelHandler(BaseHTTPRequestHandler):
    server: PanelServer
    timeout = 10

    def do_GET(self) -> None:  # pylint: disable=invalid-name
        url = urlsplit(self.path)
        query = dict(parse_qsl(url.query))
        if url.path == '/api/events':
            self._send_json(
                self.server.db.events(query.get('key'), query.get('reader'))
            )
        elif url.path == '/api/readers':
            self._send_json(self.server.db.readers())
        elif url.path == '/api/access':
            self._send_json(self.server.db.access())
        elif url.path == '/api/gateways':
            self._send_json(self.server.gateways.connected())
        elif url.path in STATIC_FILES:
            name, content_type = STATIC_FILES[url.path]
            self._send(200, content_type, (STATIC_DIR / name).read_bytes())
        else:
            self._send(404, 'text/plain; charset=utf-8', b'Not found')

    def do_POST(self) -> None:  # pylint: disable=invalid-name
        """Change a group membership: {"key"|"reader": id, "group": id, "member": bool}."""
        path = urlsplit(self.path).path
        if path not in MEMBERSHIPS:
            self._send(404, 'text/plain; charset=utf-8', b'Not found')
            return
        field, setter = MEMBERSHIPS[path]
        try:
            body = self._read_json()
            member_id, group_id, member = (
                body.get(field),
                body.get('group'),
                body.get('member'),
            )
            if not (
                isinstance(member_id, str)
                and member_id.strip()
                and isinstance(group_id, str)
                and isinstance(member, bool)
            ):
                raise BadRequest(400, f'expected {field}, group and member')
            try:
                getattr(self.server.db, setter)(member_id.strip(), group_id, member)
            except LookupError as error:
                raise BadRequest(404, str(error)) from error
        except BadRequest as error:
            self._send(error.status, 'text/plain; charset=utf-8', str(error).encode())
            return
        log.info(
            '%s: %s=%s group=%s member=%s', path, field, member_id, group_id, member
        )
        self._send(204, None, b'')

    def log_message(self, format: str, *args) -> None:  # pylint: disable=redefined-builtin
        log.debug(format, *args)

    def _read_json(self) -> dict:
        # Without authentication, these checks are what stop other web pages
        # in the admin's browser from changing access (CSRF): a cross-origin
        # page can't send application/json without a CORS preflight, which
        # this server doesn't answer, and browsers mark fetches with Origin.
        origin = self.headers.get('Origin')
        if origin is not None and origin != f'https://{self.headers.get("Host")}':
            raise BadRequest(403, 'cross-origin request')
        if self.headers.get_content_type() != 'application/json':
            raise BadRequest(415, 'expected application/json')
        try:
            length = int(self.headers.get('Content-Length', ''))
        except ValueError as error:
            raise BadRequest(411, 'Content-Length required') from error
        if not 0 <= length <= MAX_BODY:
            raise BadRequest(413, 'body too large')
        try:
            body = json.loads(self.rfile.read(length))
        except ValueError as error:
            raise BadRequest(400, 'invalid JSON') from error
        if not isinstance(body, dict):
            raise BadRequest(400, 'expected a JSON object')
        return body

    def _send_json(self, data: list[dict] | dict) -> None:
        self._send(200, 'application/json', json.dumps(data).encode())

    def _send(self, status: int, content_type: str | None, body: bytes) -> None:
        self.send_response(status)
        if content_type:
            self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
