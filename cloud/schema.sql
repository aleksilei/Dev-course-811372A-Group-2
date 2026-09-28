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
    result TEXT NOT NULL CHECK (result IN ('pass', 'fail'))
);
