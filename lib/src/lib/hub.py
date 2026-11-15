import json
import logging
import threading
from datetime import UTC, datetime

from websockets.asyncio.server import ServerConnection
from websockets.exceptions import ConnectionClosed

from lib import tls

log = logging.getLogger(__name__)

FAIL = {'result': 'fail'}


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
        # client ID -> (connection, connected since, key-exchange group)
        self._clients: dict[str, tuple[ServerConnection, str, str | None]] = {}

    def connected(self) -> list[dict]:
        with self._lock:
            return [
                {
                    'id': client_id,
                    'address': ws.remote_address[0],
                    'since': since,
                    'key_exchange': group,
                    'post_quantum': tls.is_post_quantum(group),
                }
                for client_id, (ws, since, group) in sorted(self._clients.items())
            ]

    async def handle(self, ws: ServerConnection) -> None:
        client_id = ws.request.headers.get(self.id_header, 'unknown')
        since = datetime.now(UTC).isoformat(timespec='seconds')
        group = tls.negotiated_group(ws.transport.get_extra_info('ssl_object'))
        address = ws.remote_address[0]
        session = await self.client_connected(client_id, address, since, group)
        with self._lock:
            self._clients[client_id] = (ws, since, group)
        self.changed()
        log.info(
            '%s connected from %s, key exchange %s',
            client_id,
            ws.remote_address[0],
            group,
        )
        try:
            async for message in ws:
                await ws.send(json.dumps(await self._reply(message, client_id)))
        except ConnectionClosed:
            pass
        finally:
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
