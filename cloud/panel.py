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


class PanelServer(ThreadingHTTPServer):
    """Read-only admin control panel over HTTPS (no authentication, see README)."""

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
        elif url.path == '/api/gateways':
            self._send_json(self.server.gateways.connected())
        elif url.path in STATIC_FILES:
            name, content_type = STATIC_FILES[url.path]
            self._send(200, content_type, (STATIC_DIR / name).read_bytes())
        else:
            self._send(404, 'text/plain; charset=utf-8', b'Not found')

    def log_message(self, format: str, *args) -> None:  # pylint: disable=redefined-builtin
        log.debug(format, *args)

    def _send_json(self, data: list[dict]) -> None:
        self._send(200, 'application/json', json.dumps(data).encode())

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
