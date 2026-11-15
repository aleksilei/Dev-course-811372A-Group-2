import asyncio
import logging

from cloud.db import Database
from lib import tls
from lib.hub import Hub

log = logging.getLogger(__name__)

# The fields kept of each reader a gateway reports, and at most how many.
READER_FIELDS = ('id', 'address', 'since', 'tls_version', 'cipher', 'key_exchange')
MAX_READERS = 1000


class GatewayHub(Hub):
    """Answers authorization requests forwarded by the connected gateways, and
    keeps the list of readers each one reports as connected to it."""

    id_header = 'Gateway-Id'

    def __init__(self, db: Database) -> None:
        super().__init__()
        self.db = db
        # gateway ID -> its connected readers, while the gateway is connected.
        # Gateways from before reader lists never report one.
        self._readers: dict[str, list[dict]] = {}

    def connected(self) -> list[dict]:
        """Hub.connected() rows, each with `readers`: the readers connected to
        the gateway, or None if it hasn't said."""
        gateways = super().connected()
        with self._lock:
            for gateway in gateways:
                gateway['readers'] = self._readers.get(gateway['id'])
        return gateways

    def changed(self) -> None:
        with self._lock:
            self._readers = {
                gateway_id: readers
                for gateway_id, readers in self._readers.items()
                if gateway_id in self._clients
            }

    async def respond(self, request: dict, client_id: str) -> dict:
        if request.get('type') == 'readers':
            result = self._take_readers(request.get('readers'), client_id)
            return {'request_id': request.get('request_id'), 'result': result}
        key_uuid, reader_id = request.get('id'), request.get('reader_id')
        result = 'fail'
        if isinstance(key_uuid, str) and isinstance(reader_id, str):
            # In a thread: SQLite may wait for a lock (e.g. held by sqlite-web).
            result = await asyncio.to_thread(
                self.db.authorize,
                key_uuid,
                reader_id,
                client_id,
                self.request_key_exchange(),
            )
        return {'request_id': request.get('request_id'), 'result': result}

    def _take_readers(self, readers: object, gateway_id: str) -> str:
        # Gateways aren't authenticated: keep only string fields, and a bounded
        # number of readers.
        if not (
            isinstance(readers, list)
            and len(readers) <= MAX_READERS
            and all(
                isinstance(reader, dict) and isinstance(reader.get('id'), str)
                for reader in readers
            )
        ):
            log.warning('malformed reader list from %s', gateway_id)
            return 'fail'
        kept = []
        for reader in readers:
            fields = {field: reader.get(field) for field in READER_FIELDS}
            kept.append(
                {
                    field: value if isinstance(value, str) else None
                    for field, value in fields.items()
                }
            )
        for reader in kept:
            reader['post_quantum'] = tls.is_post_quantum(reader['key_exchange'])
        kept.sort(key=lambda reader: reader['id'])
        with self._lock:
            self._readers[gateway_id] = kept
        return 'ok'
