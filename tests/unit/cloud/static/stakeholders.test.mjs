import assert from 'node:assert/strict';
import { test } from 'node:test';

import { loadPanel, plain } from './panel.mjs';

const panel = loadPanel();
const percent = panel.get('percent');
const plural = panel.get('plural');
const linkText = panel.get('linkText');
const weakenedReason = panel.get('weakenedReason');
const libraryVersions = panel.get('libraryVersions');
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

test('weakenedReason names the end whose OpenSSL breaks ML-KEM, with its version', () => {
  const vulnerable = { openssl: 'OpenSSL 3.5.7', openssl_checked: true, openssl_vulnerable: true };
  const patched = { openssl: 'OpenSSL 3.5.9', openssl_checked: true, openssl_vulnerable: false };
  const unreported = { openssl: null, openssl_checked: false, openssl_vulnerable: true };

  assert.equal(weakenedReason(vulnerable, patched),
    'vulnerable OpenSSL (gateway: OpenSSL 3.5.7: vulnerable)');
  assert.equal(weakenedReason(patched, vulnerable),
    'vulnerable OpenSSL (cloud: OpenSSL 3.5.7: vulnerable)');
  assert.equal(weakenedReason(unreported, vulnerable),
    'vulnerable OpenSSL (gateway: not reported: assumed vulnerable; cloud: OpenSSL 3.5.7: vulnerable)');
  assert.equal(weakenedReason(vulnerable, null),
    'vulnerable OpenSSL (gateway: OpenSSL 3.5.7: vulnerable)');
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
    ['#logs', { tab: 'logs', view: 'cio' }],
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

test('libraryVersions lists each OpenSSL version in use and who runs it, vulnerable first', () => {
  const old = { openssl: 'OpenSSL 3.5.7', openssl_checked: true, openssl_vulnerable: true };
  const updated = { openssl: 'OpenSSL 3.5.9', openssl_checked: true, openssl_vulnerable: false };
  const devices = {
    cloud: updated,
    devices: [
      { id: 'gw-1', ...updated },
      { id: 'gw-2', ...old },
      { id: 'rd-1', ...old },
      { id: 'rd-2', openssl: null, openssl_vulnerable: null }, // offline: left out
    ],
  };

  const rows = plain(libraryVersions(devices));

  assert.deepEqual(rows.map((row) => [row[0], row[1], row[2].text, row[3]]), [
    ['OpenSSL', 'OpenSSL 3.5.7', 'vulnerable', 'gw-2, rd-1'],
    ['OpenSSL', 'OpenSSL 3.5.9', 'patched', 'cloud, gw-1'],
  ]);
});
