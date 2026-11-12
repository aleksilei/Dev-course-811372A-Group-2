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

function fillSummary({ gateways, gatewayIds, readers, keys }) {
  const classical = gateways.filter((gateway) => gateway.post_quantum === false).length;
  const tiles = [
    ['Gateways connected', `${gateways.length} of ${gatewayIds.length}`,
      gateways.length < gatewayIds.length ? 'warn' : ''],
    ['Classical key exchange', classical, classical > 0 ? 'warn' : 'pass'],
    ['Readers', readers.length, ''],
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

// The readers the toolbar's gateway and text filters let through.
function shownReaders(readers) {
  const gateway = $('show-gateway').value;
  const text = $('show-text').value.trim().toLowerCase();
  return readers.filter((reader) => (
    (!gateway || reader.gateway_id === gateway)
    && (!text || `${reader.id} ${reader.zone_name}`.toLowerCase().includes(text))
  ));
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
    count.textContent = `${members.length} reader${members.length === 1 ? '' : 's'}`;
    summary.append(name, count, state);
    // Remember what the admin chose, not the automatic opening of a search.
    summary.addEventListener('click', () => openGateways.set(gatewayId, !details.open));

    const table = document.createElement('table');
    table.createTHead().innerHTML = '<tr><th>Reader</th><th>Zone</th></tr>';
    fillTable(table.createTBody(), members, ['id', 'zone_name']);
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
  const { gateways, events, access } = latest;
  const readers = [...latest.readers].sort(
    (a, b) => byId(a.gateway_id ?? '', b.gateway_id ?? '') || byId(a.id, b.id),
  );
  const connected = new Map(gateways.map((gateway) => [gateway.id, gateway]));
  const gatewayIds = [...new Set([
    ...readers.map((reader) => reader.gateway_id).filter(Boolean), ...connected.keys(),
  ])].sort(byId);
  const keys = [...new Set([...access.keys, ...newKeys])].sort(byId);
  const shown = shownReaders(readers);

  redraw('summary', [gateways, gatewayIds, readers.length, keys], () => fillSummary(
    { gateways, gatewayIds, readers, keys },
  ));
  redraw('gateway-choice', gatewayIds, () => fillGatewayChoice(gatewayIds));
  $('show-count').textContent = shown.length === readers.length
    ? `Showing all ${readers.length} readers`
    : `Showing ${shown.length} of ${readers.length} readers`;
  redraw('gateways', gateways, () => fillGateways(
    [...gateways].sort((a, b) => byId(a.id, b.id)),
  ));
  const opened = [...openGateways];
  redraw('readers', [shown, opened, $('show-text').value.trim() !== '', gateways], () => (
    fillReaders(shown, readers.length, connected)
  ));
  fillAccess(access, keys, shown);
  redraw('events', events, () => fillTable($('events'), events,
    ['timestamp', 'key_uuid', 'reader_id', 'zone_name', 'gateway_id', 'result']));
}

async function refresh() {
  const filter = new URLSearchParams();
  for (const name of ['key', 'reader']) {
    const value = $(name).value.trim();
    if (value) filter.set(name, value);
  }
  try {
    const [gateways, readers, events, access] = await Promise.all([
      getJSON('/api/gateways'),
      getJSON('/api/readers'),
      getJSON(`/api/events?${filter}`),
      getJSON('/api/access'),
    ]);
    latest = { gateways, readers, events, access };
    draw();
    $('status').textContent = `Updated ${new Date().toLocaleTimeString()}`;
  } catch (error) {
    $('status').textContent = `Update failed: ${error.message}`;
  }
}

$('filter').addEventListener('input', refresh);
$('filter').addEventListener('submit', (event) => event.preventDefault());
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
