CREATE TABLE IF NOT EXISTS GATEWAYS (
    id TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS READERS (
    id TEXT PRIMARY KEY,
    gateway_id TEXT NOT NULL REFERENCES GATEWAYS (id),
    zone_name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS GROUPS (
    id TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS KEY_GROUPS (
    key_uuid TEXT NOT NULL,
    group_id TEXT NOT NULL REFERENCES GROUPS (id),
    PRIMARY KEY (key_uuid, group_id)
);

CREATE TABLE IF NOT EXISTS READER_GROUPS (
    reader_id TEXT NOT NULL REFERENCES READERS (id),
    group_id TEXT NOT NULL REFERENCES GROUPS (id),
    PRIMARY KEY (reader_id, group_id)
);

-- zone_name is copied at scan time so history survives later zone changes.
CREATE TABLE IF NOT EXISTS ACCESS_EVENTS (
    timestamp TEXT NOT NULL,
    key_uuid TEXT NOT NULL,
    reader_id TEXT NOT NULL,
    zone_name TEXT,
    gateway_id TEXT NOT NULL,
    result TEXT NOT NULL CHECK (result IN ('pass', 'fail')),
    key_exchange TEXT
);

CREATE TABLE IF NOT EXISTS GATEWAY_CONNECTIONS (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    gateway_id TEXT NOT NULL,
    address TEXT NOT NULL,
    key_exchange TEXT,
    post_quantum INTEGER CHECK (post_quantum IN (0, 1) OR post_quantum IS NULL),
    connected_at TEXT NOT NULL,
    disconnected_at TEXT
);

CREATE INDEX IF NOT EXISTS gateway_connections_gateway_time
    ON GATEWAY_CONNECTIONS (gateway_id, connected_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS ACCESS_EVENTS_TIMESTAMP
    ON ACCESS_EVENTS (timestamp);
