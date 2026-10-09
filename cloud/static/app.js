'use strict';

const REFRESH_MS = 5000;

const $ = (id) => document.getElementById(id);

// Keys added in the panel that don't belong to any group yet.
const newKeys = new Set();

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

function fillGateways(gateways) {
  fillTable($('gateways'), gateways.map((gateway) => {
    const kind = KEY_EXCHANGE[gateway.post_quantum];
    return {
      ...gateway,
      key_exchange: kind ? `${gateway.key_exchange} (${kind.label})` : null,
    };
  }), ['id', 'address', 'since', 'key_exchange']);

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

// One row per row id, one column per {id, label, sublabel}; cell(row, id)
// builds each <td>.
function fillMatrix(table, corner, rows, columns, cell) {
  const head = document.createElement('tr');
  head.append(
    headerCell(corner),
    ...columns.map((column) => headerCell(column.label, column.sublabel)),
  );
  table.tHead.replaceChildren(head);
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

function fillAccess(access, readers) {
  const keys = [...new Set([...access.keys, ...newKeys])].sort();
  const keyGroups = groupsBy(access.key_groups, 'key_uuid');
  const readerGroups = groupsBy(access.reader_groups, 'reader_id');
  const rooms = readers.map((reader) => (
    { id: reader.id, label: reader.zone_name, sublabel: reader.id }
  ));
  const groups = access.groups.map((group) => ({ id: group, label: group }));

  fillMatrix($('room-access'), 'Key', keys, rooms, (key, reader) => accessCell(
    [...keyGroups(key)].filter((group) => readerGroups(reader).has(group)),
  ));
  fillMatrix($('key-groups'), 'Key', keys, groups, (key, group) => toggleCell(
    keyGroups(key).has(group), '/api/key-groups', { key, group },
    `${key} ${keyGroups(key).has(group) ? 'from' : 'to'} group ${group}`,
  ));
  fillMatrix($('reader-groups'), 'Group', access.groups, rooms, (group, reader) => toggleCell(
    readerGroups(reader).has(group), '/api/reader-groups', { reader, group },
    `group ${group} ${readerGroups(reader).has(group) ? 'from' : 'to'} reader ${reader}`,
  ));
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
    fillGateways(gateways);
    fillTable($('readers'), readers, ['id', 'gateway_id', 'zone_name']);
    fillTable($('events'), events,
      ['timestamp', 'key_uuid', 'reader_id', 'zone_name', 'gateway_id', 'result']);
    fillAccess(access, readers);
    $('status').textContent = `Updated ${new Date().toLocaleTimeString()}`;
  } catch (error) {
    $('status').textContent = `Update failed: ${error.message}`;
  }
}

$('filter').addEventListener('input', refresh);
$('filter').addEventListener('submit', (event) => event.preventDefault());
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
