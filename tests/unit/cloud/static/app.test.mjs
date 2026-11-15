import assert from 'node:assert/strict';
import { test } from 'node:test';

import { loadPanel, plain } from './panel.mjs';

const panel = loadPanel();
const byId = panel.get('byId');
const keyExchangeLabel = panel.get('keyExchangeLabel');
const connectionLabel = panel.get('connectionLabel');
const readerRows = panel.get('readerRows');
const groupsBy = panel.get('groupsBy');
const redraw = panel.get('redraw');

// An /api/devices reader row.
function reader(id, fields = {}) {
  return {
    id,
    type: 'reader',
    gateway: 'gw-1',
    registered_gateway: 'gw-1',
    zone_name: 'front-door',
    registered: true,
    state: 'connected',
    address: '10.10.0.3',
    since: 'T1',
    links: [{ key_exchange: 'X25519' }],
    ...fields,
  };
}

test('byId sorts IDs with numbers in numeric order', () => {
  assert.deepEqual(['gw-s10', 'gw-s9', 'gw-1'].sort(byId), ['gw-1', 'gw-s9', 'gw-s10']);
});

test('keyExchangeLabel names the group and its kind, or nothing if unknown', () => {
  assert.equal(
    keyExchangeLabel({ key_exchange: 'X25519MLKEM768', post_quantum: true }),
    'X25519MLKEM768 (post-quantum hybrid)',
  );
  assert.equal(keyExchangeLabel({ key_exchange: 'X25519', post_quantum: false }), 'X25519 (classical)');
  assert.equal(keyExchangeLabel({ key_exchange: null, post_quantum: null }), null);
});

test('connectionLabel: connected through its own gateway', () => {
  assert.deepEqual(plain(connectionLabel(reader('rd-1'))), {
    text: 'connected since T1',
    className: 'pass',
    title: 'from 10.10.0.3, key exchange X25519',
  });
});

test('connectionLabel: connected through another gateway', () => {
  const label = connectionLabel(reader('rd-2', { gateway: 'gw-2' }));

  assert.equal(label.text, 'connected via gw-2 since T1');
  assert.equal(label.className, 'warn');
});

test('connectionLabel: an unregistered reader fails its scans', () => {
  const label = connectionLabel(reader('rd-99', { registered: false, registered_gateway: null }));

  assert.equal(label.text, 'connected since T1, not registered: its scans fail');
  assert.equal(label.className, 'warn');
});

test('connectionLabel: an unregistered gateway is only not registered', () => {
  const gateway = { id: 'gw-9', type: 'gateway', gateway: null, registered: false,
    state: 'connected', since: 'T0', links: [] };

  assert.equal(connectionLabel(gateway).text, 'connected since T0, not registered');
});

test('connectionLabel: missing details are shown as ?', () => {
  const label = connectionLabel(reader('rd-1', { since: null, address: null, links: [] }));

  assert.equal(label.text, 'connected since ?');
  assert.equal(label.title, 'from ?, key exchange ?');
});

test('connectionLabel: not connected, offline and unknown', () => {
  assert.deepEqual(plain(connectionLabel(reader('rd-4', { state: 'not connected' }))),
    { text: 'not connected', className: 'fail' });
  assert.deepEqual(plain(connectionLabel({ type: 'gateway', state: 'offline' })),
    { text: 'offline', className: 'fail' });
  assert.deepEqual(plain(connectionLabel(reader('rd-5', { state: 'unknown' }))),
    { text: 'unknown', className: 'unknown' });
});

test('readerRows lists the readers only, under their registered gateway', () => {
  const devices = {
    devices: [
      { id: 'gw-1', type: 'gateway', state: 'connected', links: [] },
      reader('rd-10'),
      reader('rd-2', { gateway: 'gw-2' }), // connected elsewhere
      reader('rd-99', { gateway: 'gw-2', registered: false, registered_gateway: null, zone_name: null }),
      reader('rd-5', { state: 'unknown', gateway: 'gw-2', registered_gateway: 'gw-2' }),
    ],
  };

  const rows = plain(readerRows(devices));

  assert.deepEqual(rows.map((row) => [row.gateway_id, row.id]), [
    ['gw-1', 'rd-2'],
    ['gw-1', 'rd-10'],
    ['gw-2', 'rd-5'],
    ['gw-2', 'rd-99'],
  ]);
  const [rd2, , rd5, rd99] = rows;
  assert.equal(rd2.connection, 'connected via gw-2 since T1');
  assert.equal(rd2.connection_class, 'warn');
  assert.deepEqual([rd5.connected, rd5.known], [false, false]);
  assert.deepEqual([rd99.unregistered, rd99.zone_name], [true, null]);
  assert.equal(rows[1].connection_title, 'from 10.10.0.3, key exchange X25519');
});

test('groupsBy gives the groups of each member, and none for others', () => {
  const groups = groupsBy([
    { key_uuid: 'key-alice', group_id: 'staff' },
    { key_uuid: 'key-alice', group_id: 'admins' },
    { key_uuid: 'key-bob', group_id: 'staff' },
  ], 'key_uuid');

  assert.deepEqual([...groups('key-alice')].sort(), ['admins', 'staff']);
  assert.deepEqual([...groups('key-bob')], ['staff']);
  assert.equal(groups('key-nobody').size, 0);
});

test('redraw draws a part only when its data changed', () => {
  const draws = [];

  redraw('test-part', [1, 2], () => draws.push('first'));
  redraw('test-part', [1, 2], () => draws.push('same data'));
  redraw('other-part', [1, 2], () => draws.push('other part'));
  redraw('test-part', [1, 3], () => draws.push('new data'));

  assert.deepEqual(draws, ['first', 'other part', 'new data']);
});
