'use strict';

const REFRESH_MS = 5000;

const $ = (id) => document.getElementById(id);

async function getJSON(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return response.json();
}

// textContent only: IDs come from unauthenticated gateways and must not be
// interpreted as HTML.
function fillTable(tbody, rows, columns) {
  tbody.replaceChildren(...rows.map((row) => {
    const tr = document.createElement('tr');
    for (const column of columns) {
      const td = document.createElement('td');
      td.textContent = row[column] ?? '–';
      if (column === 'result') td.className = row.result;
      tr.append(td);
    }
    return tr;
  }));
}

async function refresh() {
  const filter = new URLSearchParams();
  for (const name of ['key', 'reader']) {
    const value = $(name).value.trim();
    if (value) filter.set(name, value);
  }
  try {
    const [gateways, readers, events] = await Promise.all([
      getJSON('/api/gateways'),
      getJSON('/api/readers'),
      getJSON(`/api/events?${filter}`),
    ]);
    fillTable($('gateways'), gateways, ['id', 'address', 'since']);
    fillTable($('readers'), readers, ['id', 'gateway_id', 'zone_name']);
    fillTable($('events'), events,
      ['timestamp', 'key_uuid', 'reader_id', 'zone_name', 'gateway_id', 'result']);
    $('status').textContent = `Updated ${new Date().toLocaleTimeString()}`;
  } catch (error) {
    $('status').textContent = `Update failed: ${error.message}`;
  }
}

$('filter').addEventListener('input', refresh);
$('filter').addEventListener('submit', (event) => event.preventDefault());
refresh();
setInterval(refresh, REFRESH_MS);
