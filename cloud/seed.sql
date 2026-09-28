-- Example data, loaded once when the database is first created.

INSERT INTO GATEWAYS (id) VALUES
    ('gw-1');  -- controls the readers near the main entrance

INSERT INTO READERS (id, gateway_id, zone_name) VALUES
    ('rd-1', 'gw-1', 'front-door'),
    ('rd-2', 'gw-1', 'employee-door'),
    ('rd-3', 'gw-1', 'server-room'),
    ('rd-4', 'gw-1', 'executive-room');

INSERT INTO GROUPS (id) VALUES
    ('visitors'),
    ('employees'),
    ('sysadmins'),
    ('executives');

INSERT INTO KEY_GROUPS (key_uuid, group_id) VALUES
    ('key-alice', 'employees'),
    ('key-bob', 'employees'),
    ('key-bob', 'sysadmins'),
    ('key-carol', 'executives');

INSERT INTO READER_GROUPS (reader_id, group_id) VALUES
    ('rd-1', 'visitors'),
    ('rd-1', 'employees'),
    ('rd-1', 'sysadmins'),
    ('rd-1', 'executives'),   -- front door: everyone can walk in
    ('rd-2', 'employees'),
    ('rd-2', 'sysadmins'),
    ('rd-2', 'executives'),   -- employee door: staff only
    ('rd-3', 'sysadmins'),    -- server room: sysadmins only
    ('rd-4', 'executives');   -- executive room: executives only
