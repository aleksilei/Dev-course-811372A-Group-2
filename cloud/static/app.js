'use strict';

const REFRESH_MS = 5000;
// With more readers than this, the per-gateway reader lists start collapsed.
const COLLAPSE_ABOVE = 20;

const $ = (id) => document.getElementById(id);

// Keys added in the panel that don't belong to any group yet.
const newKeys = new Set();
// Gateway id -> whether the admin opened (true) or closed (false) its readers.
const openGateways = new Map();
// What each part of the page was last drawn from, so a refresh that brings
// nothing new leaves it alone (focus, hover and scroll stay put).
const drawn = new Map();

const byId = (a, b) => a.localeCompare(b, undefined, { numeric: true });

async function getJSON(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return response.json();
}

async function postJSON(path, body) {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`${path}: HTTP ${response.status} ${await response.text()}`);
  }
}

// Calls draw() only when `data` differs from what `part` was last drawn from.
function redraw(part, data, draw) {
  const key = JSON.stringify(data);
  if (drawn.get(part) === key) return;
  drawn.set(part, key);
  draw();
}

// How a gateway's key exchange is shown, by its post_quantum flag.
const KEY_EXCHANGE = {
  true: { label: 'post-quantum hybrid', className: 'pass' },
  false: { label: 'classical', className: 'warn' },
};

// textContent only: IDs come from unauthenticated gateways and must not be
// interpreted as HTML.
function fillTable(tbody, rows, columns) {
  tbody.replaceChildren(...rows.map((row) => {
    const tr = document.createElement('tr');
    for (const column of columns) {
      const td = document.createElement('td');
      td.textContent = row[column] ?? '–';
      // Optional per-cell styling and tooltip: row.<column>_class, _title.
      if (row[`${column}_class`]) td.className = row[`${column}_class`];
      if (row[`${column}_title`]) td.title = row[`${column}_title`];
      if (column === 'result') td.className = row.result;
      if (column === 'key_exchange') {
        td.className = KEY_EXCHANGE[row.post_quantum]?.className ?? '';
      }
      tr.append(td);
    }
    return tr;
  }));
}

function keyExchangeLabel(gateway) {
  const kind = KEY_EXCHANGE[gateway.post_quantum];
  return kind ? `${gateway.key_exchange} (${kind.label})` : null;
}

function fillGateways(gateways) {
  fillTable($('gateways'), gateways.map((gateway) => (
    { ...gateway, key_exchange: keyExchangeLabel(gateway) }
  )), ['id', 'address', 'since', 'key_exchange']);

  const classical = gateways.filter((gateway) => gateway.post_quantum === false);
  let summary = '';
  if (classical.length > 0) {
    summary = `${classical.length} of ${gateways.length} gateways use classical key `
      + 'exchange: their traffic could be decrypted by a future quantum computer, '
      + 'and switching the cloud to hybrid-only would disconnect them.';
  } else if (gateways.length > 0 && gateways.every((gateway) => gateway.post_quantum)) {
    summary = 'All connected gateways use post-quantum hybrid key exchange.';
  }
  $('key-exchange-summary').textContent = summary;
}

function fillSummary({ gateways, gatewayIds, rows, keys }) {
  const classical = gateways.filter((gateway) => gateway.post_quantum === false).length;
  const registered = rows.filter((row) => !row.unregistered);
  const online = registered.filter((row) => row.connected).length;
  const unregistered = rows.length - registered.length;
  const tiles = [
    ['Gateways connected', `${gateways.length} of ${gatewayIds.length}`,
      gateways.length < gatewayIds.length ? 'warn' : ''],
    ['Classical key exchange', classical, classical > 0 ? 'warn' : 'pass'],
    ['Readers connected', `${online} of ${registered.length}`,
      online < registered.length ? 'warn' : ''],
    ...(unregistered > 0 ? [['Unregistered readers', unregistered, 'warn']] : []),
    ['Keys', keys.length, ''],
  ];
  $('summary').replaceChildren(...tiles.map(([label, value, className]) => {
    const tile = document.createElement('div');
    const dt = document.createElement('dt');
    const dd = document.createElement('dd');
    dt.textContent = label;
    dd.textContent = value;
    dd.className = className;
    tile.append(dt, dd);
    return tile;
  }));
}

// The gateway <select>: one option per gateway, keeping the current choice.
function fillGatewayChoice(gatewayIds) {
  const select = $('show-gateway');
  const chosen = select.value;
  select.replaceChildren(new Option('All gateways', ''), ...gatewayIds.map((id) => new Option(id, id)));
  select.value = gatewayIds.includes(chosen) ? chosen : '';
}

function fillConnectionGatewayChoice(connections) {
  const select = $('connection-gateway');
  const chosen = select.value;
  const gatewayIds = [...new Set([
    ...[...select.options].map((option) => option.value).filter(Boolean),
    ...connections.map((row) => row.gateway_id),
  ])].sort(byId);
  select.replaceChildren(new Option('All gateways', ''), ...gatewayIds.map((id) => new Option(id, id)));
  select.value = gatewayIds.includes(chosen) ? chosen : '';
}

// The readers the toolbar's gateway and text filters let through.
function shownReaders(readers) {
  const gateway = $('show-gateway').value;
  const text = $('show-text').value.trim().toLowerCase();
  return readers.filter((reader) => (
    (!gateway || reader.gateway_id === gateway)
    && (!text || `${reader.id} ${reader.zone_name}`.toLowerCase().includes(text))
  ));
}

// Reader ID -> its connection, from the reader lists the gateways report.
function readerConnections(gateways) {
  const connections = new Map();
  for (const gateway of gateways) {
    for (const reader of gateway.readers ?? []) {
      connections.set(reader.id, { ...reader, via: gateway.id });
    }
  }
  return connections;
}

// How a reader's connection is shown: {connection, connection_class, ...}.
function connectionOf(reader, connections, connected) {
  const connection = connections.get(reader.id);
  if (connection) {
    const elsewhere = connection.via !== reader.gateway_id;
    let text = `connected since ${connection.since ?? '?'}`;
    if (reader.unregistered) text += ', not registered: its scans fail';
    else if (elsewhere) text = `connected via ${connection.via} since ${connection.since ?? '?'}`;
    return {
      connected: true,
      connection: text,
      connection_class: reader.unregistered || elsewhere ? 'warn' : 'pass',
      connection_title: `from ${connection.address ?? '?'}, key exchange ${connection.key_exchange ?? '?'}`,
    };
  }
  const gateway = connected.get(reader.gateway_id);
  if (gateway?.readers) {
    return { connected: false, connection: 'not connected', connection_class: 'fail' };
  }
  return {
    connected: false,
    connection: gateway
      ? "unknown: gateway doesn't report its readers"
      : 'unknown: gateway not connected',
    connection_class: 'unknown',
  };
}

// The registered readers, and the connected ones the database doesn't know
// (under the gateway they're connected to), each with its connection.
function readerRows(readers, connections, connected) {
  const registered = new Set(readers.map((reader) => reader.id));
  const unregistered = [...connections.values()]
    .filter((connection) => !registered.has(connection.id))
    .map((connection) => ({
      id: connection.id, gateway_id: connection.via, zone_name: null, unregistered: true,
    }));
  return [...readers, ...unregistered]
    .map((reader) => ({ ...reader, ...connectionOf(reader, connections, connected) }))
    .sort((a, b) => byId(a.gateway_id ?? '', b.gateway_id ?? '') || byId(a.id, b.id));
}

function isOpen(gatewayId, totalReaders) {
  if ($('show-text').value.trim()) return true; // show what the search found
  return openGateways.get(gatewayId) ?? totalReaders <= COLLAPSE_ABOVE;
}

function fillReaders(readers, totalReaders, connected) {
  const byGateway = Map.groupBy(readers, (reader) => reader.gateway_id ?? '–');
  const groups = [...byGateway].map(([gatewayId, members]) => {
    const details = document.createElement('details');
    details.open = isOpen(gatewayId, totalReaders);
    const summary = document.createElement('summary');
    const name = document.createElement('strong');
    name.textContent = gatewayId;
    const state = document.createElement('span');
    const gateway = connected.get(gatewayId);
    state.textContent = gateway
      ? keyExchangeLabel(gateway) ?? 'connected'
      : 'not connected';
    state.className = gateway ? KEY_EXCHANGE[gateway.post_quantum]?.className ?? '' : 'fail';
    const count = document.createElement('span');
    count.className = 'count';
    const readers = `${members.length} reader${members.length === 1 ? '' : 's'}`;
    count.textContent = gateway?.readers
      ? `${members.filter((member) => member.connected).length} of ${readers} connected`
      : readers;
    summary.append(name, count, state);
    // Remember what the admin chose, not the automatic opening of a search.
    summary.addEventListener('click', () => openGateways.set(gatewayId, !details.open));

    const table = document.createElement('table');
    table.createTHead().innerHTML = '<tr><th>Reader</th><th>Zone</th><th>Connection</th></tr>';
    fillTable(table.createTBody(), members, ['id', 'zone_name', 'connection']);
    details.append(summary, table);
    return details;
  });
  if (groups.length === 0) {
    const none = document.createElement('p');
    none.className = 'hint';
    none.textContent = 'No reader matches the filter.';
    groups.push(none);
  }
  $('readers').replaceChildren(...groups);
}

function headerCell(text, subtext) {
  const th = document.createElement('th');
  th.textContent = text;
  if (subtext) {
    const small = document.createElement('small');
    small.textContent = subtext;
    th.append(small);
  }
  return th;
}

// One row per row id, one column per {id, label, sublabel, group}; cell(row,
// id) builds each <td>. Columns with a group get a header cell per run of the
// same group above their own.
function fillMatrix(table, corner, rows, columns, cell) {
  const head = document.createElement('tr');
  const cornerCell = headerCell(corner);
  cornerCell.className = 'corner';
  const heads = [head];
  if (columns.some((column) => column.group)) {
    const groupRow = document.createElement('tr');
    groupRow.className = 'groups';
    cornerCell.rowSpan = 2;
    groupRow.append(cornerCell);
    for (const column of columns) {
      const last = groupRow.lastElementChild;
      if (last !== cornerCell && last.dataset.group === column.group) {
        last.colSpan += 1;
      } else {
        // The label sits in a span that sticks to the left edge, so it stays
        // readable while the gateway's columns scroll past.
        const th = document.createElement('th');
        const label = document.createElement('span');
        label.textContent = column.group;
        th.append(label);
        th.dataset.group = column.group;
        groupRow.append(th);
      }
    }
    heads.unshift(groupRow);
  } else {
    head.append(cornerCell);
  }
  head.append(...columns.map((column) => headerCell(column.label, column.sublabel)));
  table.tHead.replaceChildren(...heads);
  table.tBodies[0].replaceChildren(...rows.map((row) => {
    const tr = document.createElement('tr');
    tr.append(headerCell(row), ...columns.map((column) => cell(row, column.id)));
    return tr;
  }));
}

// {member: Set of group ids} from the {<field>, group_id} rows of the API.
function groupsBy(pairs, field) {
  const index = new Map();
  for (const pair of pairs) {
    if (!index.has(pair[field])) index.set(pair[field], new Set());
    index.get(pair[field]).add(pair.group_id);
  }
  return (member) => index.get(member) ?? new Set();
}

function accessCell(sharedGroups) {
  const td = document.createElement('td');
  const granted = sharedGroups.length > 0;
  td.className = granted ? 'yes' : 'no';
  td.textContent = granted ? '✓' : '✗';
  td.title = granted ? `via ${sharedGroups.join(', ')}` : 'no shared group';
  return td;
}

function toggleCell(isMember, path, body, description) {
  const td = document.createElement('td');
  const button = document.createElement('button');
  button.className = isMember ? 'yes' : 'no';
  button.textContent = isMember ? '✓' : '✗';
  button.title = `${isMember ? 'Remove' : 'Add'} ${description}`;
  button.addEventListener('click', async () => {
    button.disabled = true;
    try {
      await postJSON(path, { ...body, member: !isMember });
      await refresh();
    } catch (error) {
      button.disabled = false;
      $('status').textContent = `Change failed: ${error.message}`;
    }
  });
  td.append(button);
  return td;
}

function fillAccess(access, keys, readers) {
  const keyGroups = groupsBy(access.key_groups, 'key_uuid');
  const readerGroups = groupsBy(access.reader_groups, 'reader_id');
  const rooms = readers.map((reader) => ({
    id: reader.id, label: reader.zone_name, sublabel: reader.id, group: reader.gateway_id,
  }));

  redraw('room-access', [access, keys, readers], () => fillMatrix(
    $('room-access'), 'Key', keys, rooms, (key, reader) => accessCell(
      [...keyGroups(key)].filter((group) => readerGroups(reader).has(group)),
    ),
  ));
  redraw('key-groups', [access.key_groups, access.groups, keys], () => fillMatrix(
    $('key-groups'), 'Key', keys, access.groups.map((group) => ({ id: group, label: group })),
    (key, group) => toggleCell(
      keyGroups(key).has(group), '/api/key-groups', { key, group },
      `${key} ${keyGroups(key).has(group) ? 'from' : 'to'} group ${group}`,
    ),
  ));
  redraw('reader-groups', [access.reader_groups, access.groups, readers], () => fillMatrix(
    $('reader-groups'), 'Group', access.groups, rooms, (group, reader) => toggleCell(
      readerGroups(reader).has(group), '/api/reader-groups', { reader, group },
      `group ${group} ${readerGroups(reader).has(group) ? 'from' : 'to'} reader ${reader}`,
    ),
  ));
}

// The data of the last refresh, so that the toolbar filters redraw at once.
let latest = null;

function draw() {
  if (!latest) return;
  const { gateways, events, access, connections } = latest;
  const connected = new Map(gateways.map((gateway) => [gateway.id, gateway]));
  // Registered readers, plus connected ones the database doesn't know.
  const rows = readerRows(latest.readers, readerConnections(gateways), connected);
  const gatewayIds = [...new Set([
    ...rows.map((reader) => reader.gateway_id).filter(Boolean), ...connected.keys(),
  ])].sort(byId);
  const keys = [...new Set([...access.keys, ...newKeys])].sort(byId);
  const shownRows = shownReaders(rows);
  const shown = shownRows.filter((row) => !row.unregistered);

  redraw('summary', [gateways, gatewayIds, rows, keys], () => fillSummary(
    { gateways, gatewayIds, rows, keys },
  ));
  redraw('gateway-choice', gatewayIds, () => fillGatewayChoice(gatewayIds));
  $('show-count').textContent = shownRows.length === rows.length
    ? `Showing all ${rows.length} readers`
    : `Showing ${shownRows.length} of ${rows.length} readers`;
  redraw('gateways', gateways, () => fillGateways(
    [...gateways].sort((a, b) => byId(a.id, b.id)),
  ));
  const opened = [...openGateways];
  redraw('readers', [shownRows, opened, $('show-text').value.trim() !== '', gateways], () => (
    fillReaders(shownRows, rows.length, connected)
  ));
  fillAccess(access, keys, shown);
  redraw('events', events, () => fillTable($('events'), events,
    ['timestamp', 'key_uuid', 'reader_id', 'zone_name', 'gateway_id', 'result']));
  if (window.location.hash === '#logs') {
    fillConnectionGatewayChoice(connections);
    redraw('connections', connections, () => fillTable($('connections'), connections.map((row) => ({
      ...row,
      key_exchange: row.key_exchange ?? 'unknown',
      pqc: row.post_quantum === null ? 'unknown' : row.post_quantum ? 'yes' : 'no',
    })), ['gateway_id', 'address', 'key_exchange', 'pqc', 'connected_at', 'disconnected_at']));
  }
}

async function refresh() {
  const filter = new URLSearchParams();
  for (const name of ['key', 'reader']) {
    const value = $(name).value.trim();
    if (value) filter.set(name, value);
  }
  const selectedGateway = $('connection-gateway').value;
  const connectionFilter = new URLSearchParams();
  if (selectedGateway) connectionFilter.set('gateway', selectedGateway);
  const onLogsTab = window.location.hash === '#logs';
  try {
    const [gateways, readers, events, access, connections] = await Promise.all([
      getJSON('/api/gateways'),
      getJSON('/api/readers'),
      getJSON(`/api/events?${filter}`),
      getJSON('/api/access'),
      onLogsTab ? getJSON(`/api/connections?${connectionFilter}`) : Promise.resolve([]),
    ]);
    latest = { gateways, readers, events, access, connections };
    draw();
    $('status').textContent = `Updated ${new Date().toLocaleTimeString()}`;
  } catch (error) {
    $('status').textContent = `Update failed: ${error.message}`;
  }
}

$('filter').addEventListener('input', refresh);
$('filter').addEventListener('submit', (event) => event.preventDefault());
$('connection-filter').addEventListener('input', refresh);
$('connection-filter').addEventListener('submit', (event) => event.preventDefault());
$('connection-gateway').addEventListener('change', refresh);
window.addEventListener('hashchange', refresh);
$('show').addEventListener('input', draw);
$('show').addEventListener('submit', (event) => event.preventDefault());
$('add-key').addEventListener('submit', (event) => {
  event.preventDefault();
  const key = $('new-key').value.trim();
  if (!key) return;
  newKeys.add(key);
  $('new-key').value = '';
  refresh();
});
refresh();
setInterval(refresh, REFRESH_MS);
