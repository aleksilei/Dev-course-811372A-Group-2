import json
import logging
import threading
from contextvars import ContextVar
from datetime import UTC, datetime

from websockets.asyncio.server import ServerConnection
from websockets.exceptions import ConnectionClosed

from lib import openssl, tls

log = logging.getLogger(__name__)

FAIL = {'result': 'fail'}

# The fields of each connected() row that a gateway reports to the cloud about
# its readers (see gateway.readers and cloud.gateways).
REPORTED_FIELDS = (
    'id',
    'address',
    'since',
    'tls_version',
    'cipher',
    'key_exchange',
    'openssl',
)


class Hub:
    """Server end of a WebSocket hop.

    Keeps every connected client in memory, keyed by the ID it sends in the
    `id_header` handshake header, and answers each JSON request with the reply
    from respond(). The ID is taken on trust: clients are not authenticated.
    changed() is called whenever a client connects or disconnects.
    """

    id_header = 'Client-Id'

    def __init__(self) -> None:
        # connected() may be called from other threads (the cloud's panel).
        # The lock is never held across an await.
        self._lock = threading.Lock()
        # client ID -> (connection, connected since, tls.link_details() and
        # the client's reported OpenSSL version)
        self._clients: dict[str, tuple[ServerConnection, str, dict]] = {}
        self._request_link: ContextVar[dict | None] = ContextVar(
            'request_link', default=None
        )

    def request_link(self) -> dict:
        """Details of the connection handling this request, even during reconnects."""
        return self._request_link.get() or {}

    def connected(self) -> list[dict]:
        with self._lock:
            return [
                {
                    'id': client_id,
                    'address': ws.remote_address[0],
                    'since': since,
                    **link,
                    'post_quantum': tls.is_post_quantum(link['key_exchange']),
                    **openssl.details(link['openssl']),
                }
                for client_id, (ws, since, link) in sorted(self._clients.items())
            ]

    async def handle(self, ws: ServerConnection) -> None:
        client_id = ws.request.headers.get(self.id_header, 'unknown')
        since = datetime.now(UTC).isoformat(timespec='seconds')
        # Read on the event loop, which owns the connection: connected() is also
        # called from other threads.
        link = {
            **tls.link_details(ws.transport.get_extra_info('ssl_object')),
            'openssl': openssl.reported(ws.request.headers.get(openssl.OPENSSL_HEADER)),
        }
        group = link['key_exchange']
        address = ws.remote_address[0]
        session = await self.client_connected(client_id, address, since, group)
        with self._lock:
            self._clients[client_id] = (ws, since, link)
        self.changed()
        log.info(
            '%s connected from %s, key exchange %s',
            client_id,
            ws.remote_address[0],
            group,
        )
        token = self._request_link.set(link)
        try:
            async for message in ws:
                await ws.send(json.dumps(await self._reply(message, client_id)))
        except ConnectionClosed:
            pass
        finally:
            self._request_link.reset(token)
            with self._lock:
                removed = self._clients.get(client_id, (None,))[0] is ws
                if removed:
                    del self._clients[client_id]
            if removed:
                self.changed()
            await self.client_disconnected(session)
            log.info('%s disconnected', client_id)

    # pylint: disable=unused-argument
    async def client_connected(
        self, client_id: str, address: str, since: str, group: str | None
    ) -> object | None:
        """Hook for subclasses that need to persist each individual session."""
        return None

    async def client_disconnected(self, session: object | None) -> None:
        """Hook called when this specific websocket session ends."""

    async def respond(self, request: dict, client_id: str) -> dict:
        raise NotImplementedError

    def changed(self) -> None:
        """Called on the event loop after a client connected or disconnected."""

    async def _reply(self, message: str | bytes, client_id: str) -> dict:
        try:
            request = json.loads(message)
        except ValueError:
            request = None
        if not isinstance(request, dict):
            log.warning('malformed request from %s', client_id)
            return FAIL
        return await self.respond(request, client_id)
