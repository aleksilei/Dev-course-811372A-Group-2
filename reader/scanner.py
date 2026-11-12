import asyncio
import json
import logging
import random
import ssl
from collections.abc import Awaitable, Callable, Sequence

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import WebSocketException

from reader.interval import ScanInterval

log = logging.getLogger(__name__)


class GatewayClient:
    """This reader's WebSocket connection to its gateway.

    The connection is opened on the first request and reopened on the next
    request after any failure.
    """

    def __init__(
        self,
        uri: str,
        reader_id: str,
        context: ssl.SSLContext | None,
        timeout: float = 5.0,
    ) -> None:
        self.uri = uri
        self.reader_id = reader_id
        self.context = context
        self.timeout = timeout
        self._ws: ClientConnection | None = None

    async def authorize(self, key_uuid: str) -> bool:
        """Ask the gateway whether key_uuid may pass; any failure means no."""
        try:
            async with asyncio.timeout(self.timeout):
                if self._ws is None:
                    self._ws = await connect(
                        self.uri,
                        ssl=self.context,
                        additional_headers={'Reader-Id': self.reader_id},
                    )
                request = {'id': key_uuid, 'reader_id': self.reader_id}
                await self._ws.send(json.dumps(request))
                reply = json.loads(await self._ws.recv())
        except (OSError, WebSocketException, ValueError) as error:
            log.warning('no answer from gateway: %r', error)
            await self.close()
            return False
        return isinstance(reply, dict) and reply.get('result') == 'pass'

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None


def unlock(zone: str) -> None:
    log.info('UNLOCK %s (stub, no physical lock attached)', zone)


async def scan(client: GatewayClient, key_uuid: str, zone: str) -> bool:
    """Simulate presenting a key to this reader and log the outcome."""
    granted = await client.authorize(key_uuid)
    outcome = 'PASS' if granted else 'FAIL'
    log.info('%s key=%s reader=%s zone=%s', outcome, key_uuid, client.reader_id, zone)
    if granted:
        unlock(zone)
    return granted


async def scan_forever(
    client: GatewayClient,
    keys: Sequence[str],
    zone: str,
    interval: ScanInterval,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Scan a random key, wait interval.next() seconds, and repeat."""
    while True:
        await scan(client, random.choice(keys), zone)
        await sleep(interval.next())
