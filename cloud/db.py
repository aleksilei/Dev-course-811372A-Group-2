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

# Keys exist only through their groups, so also list keys seen at a reader:
# the admin can then grant access to a key that was just turned away.
KEYS = """
SELECT key_uuid FROM KEY_GROUPS
UNION
SELECT key_uuid FROM ACCESS_EVENTS
ORDER BY key_uuid
"""

# Group memberships of keys and readers, keyed by the column that holds the
# member. The table and column names are constants, never user input.
MEMBERSHIP_TABLES = {'key_uuid': 'KEY_GROUPS', 'reader_id': 'READER_GROUPS'}


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

    def access(self) -> dict:
        """Everything the panel needs to show and edit who may open which reader."""
        with self._connect() as conn:
            return {
                'keys': [row['key_uuid'] for row in conn.execute(KEYS)],
                'groups': [
                    row['id']
                    for row in conn.execute('SELECT id FROM GROUPS ORDER BY id')
                ],
                'key_groups': [
                    dict(row)
                    for row in conn.execute(
                        'SELECT key_uuid, group_id FROM KEY_GROUPS'
                        ' ORDER BY key_uuid, group_id'
                    )
                ],
                'reader_groups': [
                    dict(row)
                    for row in conn.execute(
                        'SELECT reader_id, group_id FROM READER_GROUPS'
                        ' ORDER BY reader_id, group_id'
                    )
                ],
            }

    def set_key_group(self, key_uuid: str, group_id: str, member: bool) -> None:
        """Add a key to a group or remove it. Raises LookupError for unknown groups."""
        self._set_membership('key_uuid', key_uuid, group_id, member)

    def set_reader_group(self, reader_id: str, group_id: str, member: bool) -> None:
        """Add a reader to a group or remove it. Raises LookupError for unknown
        readers and groups."""
        self._set_membership('reader_id', reader_id, group_id, member)

    def _set_membership(
        self, column: str, member_id: str, group_id: str, member: bool
    ) -> None:
        table = MEMBERSHIP_TABLES[column]
        params = {'member_id': member_id, 'group_id': group_id}
        with self._connect() as conn:
            # SQLite doesn't enforce the REFERENCES clauses unless asked to.
            if not conn.execute(
                'SELECT 1 FROM GROUPS WHERE id = :group_id', params
            ).fetchone():
                raise LookupError(f'unknown group {group_id!r}')
            if (
                column == 'reader_id'
                and not conn.execute(
                    'SELECT 1 FROM READERS WHERE id = :member_id', params
                ).fetchone()
            ):
                raise LookupError(f'unknown reader {member_id!r}')
            if member:
                conn.execute(
                    f'INSERT OR IGNORE INTO {table} ({column}, group_id)'
                    ' VALUES (:member_id, :group_id)',
                    params,
                )
            else:
                conn.execute(
                    f'DELETE FROM {table}'
                    f' WHERE {column} = :member_id AND group_id = :group_id',
                    params,
                )

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
