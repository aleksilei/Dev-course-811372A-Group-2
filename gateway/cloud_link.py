import asyncio
import json
import logging
import ssl
import uuid

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import WebSocketException

from lib import tls
from lib.hub import FAIL

log = logging.getLogger(__name__)


class CloudLink:
    """The gateway's single WebSocket connection to the cloud, shared by all readers.

    run() keeps the connection open (reconnecting after failures) and routes
    every reply to the request with the same request_id.
    """

    def __init__(
        self,
        uri: str,
        gateway_id: str,
        context: ssl.SSLContext | None,
        timeout: float = 5.0,
        retry_delay: float = 3.0,
    ) -> None:
        self.uri = uri
        self.gateway_id = gateway_id
        self.context = context
        self.timeout = timeout
        self.retry_delay = retry_delay
        self._ws: ClientConnection | None = None
        self._pending: dict[str, asyncio.Future] = {}

    @property
    def connected(self) -> bool:
        return self._ws is not None

    async def run(self) -> None:
        while True:
            try:
                async with connect(
                    self.uri,
                    ssl=self.context,
                    additional_headers={'Gateway-Id': self.gateway_id},
                    open_timeout=self.timeout,
                ) as ws:
                    self._ws = ws
                    log.info(
                        'connected to cloud at %s, key exchange %s',
                        self.uri,
                        tls.negotiated_group(ws.transport.get_extra_info('ssl_object')),
                    )
                    async for message in ws:
                        self._dispatch(message)
            except (OSError, WebSocketException) as error:
                log.warning('cloud connection failed: %r', error)
            finally:
                self._ws = None
            await asyncio.sleep(self.retry_delay)

    async def request(self, request: dict) -> dict:
        """Forward one request and wait for its reply; fails closed."""
        ws = self._ws
        if ws is None:
            return FAIL
        request_id = uuid.uuid4().hex
        reply = self._pending[request_id] = asyncio.get_running_loop().create_future()
        try:
            await ws.send(json.dumps({**request, 'request_id': request_id}))
            return await asyncio.wait_for(reply, self.timeout)
        except (TimeoutError, WebSocketException):
            return FAIL
        finally:
            del self._pending[request_id]

    def _dispatch(self, message: str | bytes) -> None:
        try:
            reply = json.loads(message)
            request_id = reply['request_id']
        except (ValueError, TypeError, KeyError):
            request_id = None
        # request() only sends string IDs. Anything else is malformed, and a
        # list or object can't even be looked up (TypeError would end run()).
        if not isinstance(request_id, str):
            log.warning('ignoring malformed reply from cloud')
            return
        future = self._pending.get(request_id)
        if future is not None and not future.done():
            future.set_result(reply)
