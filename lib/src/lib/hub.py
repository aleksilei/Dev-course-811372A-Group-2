import json
import logging
import threading
from datetime import UTC, datetime

from websockets.asyncio.server import ServerConnection
from websockets.exceptions import ConnectionClosed

log = logging.getLogger(__name__)

FAIL = {'result': 'fail'}


class Hub:
    """Server end of a WebSocket hop.

    Keeps every connected client in memory, keyed by the ID it sends in the
    `id_header` handshake header, and answers each JSON request with the reply
    from respond(). The ID is taken on trust: clients are not authenticated.
    """

    id_header = 'Client-Id'

    def __init__(self) -> None:
        # connected() may be called from other threads (the cloud's panel).
        # The lock is never held across an await.
        self._lock = threading.Lock()
        self._clients: dict[str, tuple[ServerConnection, str]] = {}

    def connected(self) -> list[dict]:
        with self._lock:
            return [
                {'id': client_id, 'address': ws.remote_address[0], 'since': since}
                for client_id, (ws, since) in sorted(self._clients.items())
            ]

    async def handle(self, ws: ServerConnection) -> None:
        client_id = ws.request.headers.get(self.id_header, 'unknown')
        since = datetime.now(UTC).isoformat(timespec='seconds')
        with self._lock:
            self._clients[client_id] = (ws, since)
        log.info('%s connected from %s', client_id, ws.remote_address[0])
        try:
            async for message in ws:
                await ws.send(json.dumps(await self._reply(message, client_id)))
        except ConnectionClosed:
            pass
        finally:
            with self._lock:
                if self._clients.get(client_id, (None,))[0] is ws:
                    del self._clients[client_id]
            log.info('%s disconnected', client_id)

    async def respond(self, request: dict, client_id: str) -> dict:
        raise NotImplementedError

    async def _reply(self, message: str | bytes, client_id: str) -> dict:
        try:
            request = json.loads(message)
        except ValueError:
            request = None
        if not isinstance(request, dict):
            log.warning('malformed request from %s', client_id)
            return FAIL
        return await self.respond(request, client_id)
