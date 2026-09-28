import asyncio

from cloud.db import Database
from lib.hub import Hub


class GatewayHub(Hub):
    """Answers authorization requests forwarded by the connected gateways."""

    id_header = 'Gateway-Id'

    def __init__(self, db: Database) -> None:
        super().__init__()
        self.db = db

    async def respond(self, request: dict, client_id: str) -> dict:
        key_uuid, reader_id = request.get('id'), request.get('reader_id')
        result = 'fail'
        if isinstance(key_uuid, str) and isinstance(reader_id, str):
            # In a thread: SQLite may wait for a lock (e.g. held by sqlite-web).
            result = await asyncio.to_thread(
                self.db.authorize, key_uuid, reader_id, client_id
            )
        return {'request_id': request.get('request_id'), 'result': result}
