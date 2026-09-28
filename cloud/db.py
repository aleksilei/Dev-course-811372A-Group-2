import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = Path(__file__).with_name('schema.sql')
SEED = Path(__file__).with_name('seed.sql')

AUTHORIZE = """
SELECT 1
FROM KEY_GROUPS kg
JOIN READER_GROUPS rg ON kg.group_id = rg.group_id
WHERE kg.key_uuid = :key_uuid
  AND rg.reader_id = :reader_id
LIMIT 1
"""

LOG_EVENT = """
INSERT INTO ACCESS_EVENTS
    (timestamp, key_uuid, reader_id, zone_name, gateway_id, result)
VALUES (
    :timestamp, :key_uuid, :reader_id,
    (SELECT zone_name FROM READERS WHERE id = :reader_id),
    :gateway_id, :result
)
"""

EVENTS = """
SELECT timestamp, key_uuid, reader_id, zone_name, gateway_id, result
FROM ACCESS_EVENTS
WHERE (:key_uuid IS NULL OR key_uuid = :key_uuid)
  AND (:reader_id IS NULL OR reader_id = :reader_id)
ORDER BY rowid DESC
LIMIT :limit
"""


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = path

    def init(self) -> None:
        """Create missing tables; load the example data into a brand-new DB."""
        with self._connect() as conn:
            is_new = not conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'GATEWAYS'"
            ).fetchone()
            conn.executescript(SCHEMA.read_text(encoding='utf-8'))
            if is_new:
                conn.executescript(SEED.read_text(encoding='utf-8'))

    def authorize(self, key_uuid: str, reader_id: str, gateway_id: str) -> str:
        """Return 'pass' or 'fail' and record the attempt as an access event."""
        with self._connect() as conn:
            params = {'key_uuid': key_uuid, 'reader_id': reader_id}
            result = 'pass' if conn.execute(AUTHORIZE, params).fetchone() else 'fail'
            conn.execute(
                LOG_EVENT,
                {
                    **params,
                    'timestamp': datetime.now(UTC).isoformat(timespec='seconds'),
                    'gateway_id': gateway_id,
                    'result': result,
                },
            )
        return result

    def events(
        self,
        key_uuid: str | None = None,
        reader_id: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Newest access events first, optionally filtered by key and/or reader."""
        params = {'key_uuid': key_uuid, 'reader_id': reader_id, 'limit': limit}
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(EVENTS, params)]

    def readers(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                'SELECT id, gateway_id, zone_name FROM READERS ORDER BY id'
            )
            return [dict(row) for row in rows]

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        # One short-lived connection per call keeps the threaded servers safe.
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            with conn:  # commit on success, roll back on error
                yield conn
        finally:
            conn.close()
