import assert from 'node:assert/strict';
import { test } from 'node:test';

import { loadPanel, plain } from './panel.mjs';

const panel = loadPanel();
const percent = panel.get('percent');
const plural = panel.get('plural');
const linkText = panel.get('linkText');
const statusCounts = panel.get('statusCounts');
const route = panel.get('route');
const DEVICE_STATUS = panel.get('DEVICE_STATUS');

test('percent rounds a share, and shows a dash when there is none', () => {
  assert.equal(percent(0.5), '50%');
  assert.equal(percent(1 / 3), '33%');
  assert.equal(percent(0), '0%');
  assert.equal(percent(null), '–');
});

test('plural adds an s to anything but one', () => {
  assert.equal(plural(1, 'gateway'), '1 gateway');
  assert.equal(plural(0, 'gateway'), '0 gateways');
  assert.equal(plural(3, 'door'), '3 doors');
});

test('linkText describes a link, with what is unknown marked', () => {
  const link = { key_exchange: 'X25519MLKEM768', post_quantum: true,
    tls_version: 'TLSv1.3', cipher: 'TLS_AES_256_GCM_SHA384' };

  assert.equal(linkText(link), 'X25519MLKEM768 (post-quantum), TLSv1.3, TLS_AES_256_GCM_SHA384');
  assert.equal(linkText({ ...link, key_exchange: 'X25519', post_quantum: false }),
    'X25519 (classical), TLSv1.3, TLS_AES_256_GCM_SHA384');
  assert.equal(linkText({ key_exchange: null, post_quantum: null }), 'unknown (unknown), ?, ?');
  assert.equal(linkText(null), '–');
});

test('statusCounts lists each status in the given order', () => {
  const counts = { 'post-quantum': 1, classical: 5, unknown: 0, offline: 2 };

  assert.equal(statusCounts(counts, ['post-quantum', 'classical', 'unknown', 'offline']),
    '1 post-quantum, 5 classical, 0 unknown, 2 offline');
});

test('every device status has one of the existing colours', () => {
  assert.deepEqual(plain(DEVICE_STATUS),
    { 'post-quantum': 'pass', classical: 'warn', unknown: '', offline: 'fail' });
});

test('route reads the tab and view from the URL, defaulting what it does not know', () => {
  const cases = [
    ['', { tab: 'operations', view: 'cio' }],
    ['#operations', { tab: 'operations', view: 'cio' }],
    ['#stakeholders', { tab: 'stakeholders', view: 'cio' }],
    ['#stakeholders/security', { tab: 'stakeholders', view: 'security' }],
    ['#stakeholders/migration', { tab: 'stakeholders', view: 'migration' }],
    ['#stakeholders/nobody', { tab: 'stakeholders', view: 'cio' }],
    ['#elsewhere/security', { tab: 'operations', view: 'security' }],
  ];
  for (const [hash, expected] of cases) {
    panel.context.window.location.hash = hash;
    assert.deepEqual(plain(route()), expected, hash);
  }
});
