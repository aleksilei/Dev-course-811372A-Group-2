'use strict';

// Tabs (#operations, #logs, #stakeholders/<view>) and the stakeholder views, drawn
// from /api/summary and /api/devices. Loaded after app.js, whose $(),
// getJSON(), redraw() and connectionLabel() it uses.

const SUMMARY_MS = 5000;
const DEFAULT_VIEW = 'cio';

const STATUS = {
  green: { label: 'On track', text: 'Every site gateway is connected and uses quantum-safe encryption.' },
  amber: { label: 'Needs attention', text: 'The transition is under way, but some sites still need work.' },
  red: { label: 'Action needed', text: 'Some sites need action now: see the top risks below.' },
};

// textContent only: gateway IDs come from unauthenticated gateways.
function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  const { text, ...attributes } = props;
  Object.assign(node, attributes);
  if (text !== undefined) node.textContent = text;
  node.append(...children);
  return node;
}

const percent = (share) => (share === null ? '–' : `${Math.round(share * 100)}%`);
const plural = (count, word) => `${count} ${word}${count === 1 ? '' : 's'}`;

function statusBadge(status, label = STATUS[status].label) {
  return el('span', { className: `badge ${status}`, text: label });
}

// A cell is text, or {text, className} to colour it with the panel's classes.
function table(headers, rows) {
  const body = el('tbody');
  for (const row of rows) {
    body.append(el('tr', {}, ...row.map((cell) => (
      cell !== null && typeof cell === 'object' ? el('td', cell) : el('td', { text: cell ?? '–' })
    ))));
  }
  return el('div', { className: 'scroll' }, el('table', {},
    el('thead', {}, el('tr', {}, ...headers.map((header) => el('th', { text: header })))),
    body));
}

// How a device's encryption status is shown, in the panel's existing colours.
const DEVICE_STATUS = {
  'post-quantum': 'pass',
  classical: 'warn',
  unknown: '',
  offline: 'fail',
};

// "X25519MLKEM768 (post-quantum), TLSv1.3, TLS_AES_256_GCM_SHA384"
function linkText(link) {
  if (!link) return '–';
  const kind = { true: 'post-quantum', false: 'classical' }[link.post_quantum] ?? 'unknown';
  return `${link.key_exchange ?? 'unknown'} (${kind}), ${link.tls_version ?? '?'}, ${link.cipher ?? '?'}`;
}

// Why a weakened gateway (SCRUM-51) is no stronger than classical: the
// vulnerable OpenSSL at its end, the cloud's, or both, worded as in the
// Operations tab (app.js). gateway is its /api/devices row, cloud the
// cloud's own OpenSSL details.
function weakenedReason(gateway, cloud) {
  const ends = [['gateway', gateway], ['cloud', cloud]]
    .filter(([, device]) => device?.openssl_vulnerable === true)
    .map(([who, device]) => `${who}: ${opensslLabel(device).text}`);
  return `vulnerable OpenSSL (${ends.join('; ') || 'unknown'})`;
}

// The encryption library versions in use: one row per OpenSSL version that
// the cloud or a connected device runs, with who runs it. Vulnerable or
// unreported versions first. Offline devices report nothing and are left out.
function libraryVersions(devices) {
  const holders = [
    ...(devices.cloud ? [{ ...devices.cloud, id: 'cloud' }] : []),
    ...devices.devices.filter((device) => device.openssl_vulnerable !== null),
  ];
  const rows = new Map();
  for (const device of holders) {
    const key = device.openssl ?? '';
    if (!rows.has(key)) rows.set(key, { device, ids: [] });
    rows.get(key).ids.push(device.id);
  }
  return [...rows.values()]
    .sort((a, b) => Number(b.device.openssl_vulnerable) - Number(a.device.openssl_vulnerable))
    .map(({ device, ids }) => {
      const label = opensslLabel(device); // from app.js
      return [
        'OpenSSL',
        device.openssl ?? 'not reported',
        { text: device.openssl_vulnerable ? 'vulnerable' : 'patched',
          className: device.openssl_vulnerable ? 'warn' : 'pass', title: label.title ?? '' },
        ids.join(', '),
      ];
    });
}

function statusCounts(counts, statuses) {
  return statuses.map((status) => `${counts[status]} ${status}`).join(', ');
}

// The encryption status of every device (SCRUM-18): one row per gateway and
// reader, its own link, and for readers also their gateway's link to the cloud.
// weakened: the IDs of hybrid gateways on a vulnerable OpenSSL (SCRUM-51),
// shown as classical, as in the CIO and migration views.
function deviceStatus(devices, weakened = new Set()) {
  if (!devices) return [el('p', { text: 'Loading…' })];
  const statusOf = (device) => (device.type === 'gateway' && weakened.has(device.id)
    && device.status === 'post-quantum' ? 'classical' : device.status);
  const counts = { gateway: {}, reader: {} };
  for (const type of Object.keys(counts)) {
    for (const status of devices.statuses) counts[type][status] = 0;
  }
  for (const device of devices.devices) counts[device.type][statusOf(device)] += 1;
  const own = (device) => device.links[0];
  const upstream = (device) => (device.type === 'reader' ? device.links[1] : null);
  // The OpenSSL a device reports (SCRUM-51), worded and coloured as in the
  // Operations tab; hover for the advisory.
  const opensslCellOf = (device) => {
    const label = opensslLabel(device); // from app.js
    return { text: label.text ?? '–', className: label.className, title: label.title ?? '' };
  };
  const cloud = devices.cloud ? opensslLabel(devices.cloud) : null;
  const versions = libraryVersions(devices);
  return [
    el('h3', { text: 'Encryption library versions' }),
    el('p', { className: 'hint', text: 'The OpenSSL version the cloud and every connected device run. '
      + 'OpenSSL does all of their TLS, including the hybrid ML-KEM key exchange. Versions before 3.5.8 '
      + '(such as the old 3.5.7) have the ML-KEM vulnerability; the updated 3.5.9 is patched. A device '
      + 'that reports no version is assumed vulnerable.' }),
    versions.length
      ? table(['Library', 'Version', 'Status', 'Used by'], versions)
      : el('p', { text: 'No connected device has reported a version.' }),
    el('h3', { text: 'Encryption status of every device' }),
    el('p', { className: 'hint', text: `Gateways: ${statusCounts(counts.gateway, devices.statuses)}. `
      + `Readers: ${statusCounts(counts.reader, devices.statuses)}. A device is as strong as its `
      + 'weakest link: reader traffic crosses the classical reader → gateway hop (per the spec) and its '
      + "gateway's link to the cloud. A hybrid gateway on a vulnerable OpenSSL, at its end or the cloud's, "
      + 'is no stronger than classical.' }),
    table(['Device', 'Type', 'Gateway', 'Status', 'OpenSSL', 'Own link', "Gateway's link to the cloud",
      'Connection'],
    devices.devices.map((device) => [
      device.id,
      device.type,
      device.gateway ?? '–',
      statusOf(device) === device.status
        ? { text: device.status, className: DEVICE_STATUS[device.status] }
        : { text: 'classical (vulnerable OpenSSL)', className: DEVICE_STATUS.classical },
      opensslCellOf(device),
      linkText(own(device)),
      device.type === 'reader' ? linkText(upstream(device)) : '–',
      connectionLabel(device), // from app.js, as in the Readers list
    ])),
    ...(cloud?.text ? [el('p', { className: `hint ${cloud.className}`.trim(), title: cloud.title ?? '',
      text: `The cloud's own OpenSSL, at the other end of every gateway link: ${cloud.text}.` })] : []),
    el('p', { className: 'hint', text: `This control panel: ${linkText(devices.panel)}.` }),
  ];
}

function concerns({ addressed, notYet, wont }) {
  const column = (title, className, items) => el('div', { className: `concern ${className}` },
    el('h4', { text: title }),
    el('ul', {}, ...items.map((item) => el('li', { text: item }))));
  return el('section', { className: 'concerns' },
    el('h3', { text: 'Your concerns' }),
    el('div', { className: 'concern-columns' },
      column('Addressed', 'addressed', addressed),
      column('Not yet addressed', 'not-yet', notYet),
      column('Will not be addressed here', 'wont', wont)));
}

// Each view: who it is for, their question, how to draw it, and an honest
// account of their concerns (persona cards, 811373A).
const VIEWS = {
  cio: {
    title: 'CIO',
    question: 'Do I need to worry?',
    draw(summary) {
      const { gateways } = summary;
      const risks = summary.risks.slice(0, 3);
      return [
        el('div', { className: `headline ${summary.status}` },
          statusBadge(summary.status),
          el('p', { text: STATUS[summary.status].text })),
        el('p', { className: 'big-line', text: gateways.connected
          ? `${gateways.hybrid} of ${plural(gateways.connected, 'connected site gateway')} `
            + 'protected against future quantum attacks.'
          : 'No site gateway is connected right now.' }),
        el('h3', { text: 'Top risks' }),
        risks.length
          ? el('ol', { className: 'risks' }, ...risks.map((risk) => el('li', { className: risk.severity },
            el('strong', { text: risk.title }), el('span', { text: risk.detail }))))
          : el('p', { text: 'No open risks.' }),
        el('p', { className: 'hint', text: 'This view leaves out internal details such as addresses '
          + 'and device names, so it can be shown to customers.' }),
      ];
    },
    concerns: {
      addressed: [
        'A green / amber / red status for the post-quantum transition.',
        'The top three risks in plain language.',
        'Library vulnerabilities: a gateway on a vulnerable OpenSSL counts as classical and is a top risk.',
        'A view to show our key customer where we stand.',
      ],
      notYet: [
        'Hearing about problems before the board does: the panel has no notifications yet, '
          + 'it has to be opened.',
        'Progress against the key customer contract deadline: the deadline is not in the system yet.',
      ],
      wont: [
        'Budget and cost estimates: decided outside the dashboard.',
      ],
    },
  },

  migration: {
    title: 'PQC migration',
    question: 'How close are we to PQC readiness, and what is blocking us?',
    draw(summary) {
      const { gateways } = summary;
      const trafficNote = summary.readiness === null
        ? 'No access events in the last hour; traffic readiness is unavailable. '
        : 'Counts access events in the last hour that used hybrid key exchange '
          + 'with patched OpenSSL at both ends. ';
      const blockers = [
        ...summary.classical.map((g) => [
          g.id, 'classical key exchange', g.readers, percent(g.traffic_share), 'upgrade or replace',
        ]),
        // Hybrid, but on an OpenSSL whose ML-KEM is vulnerable (SCRUM-51).
        ...summary.weakened.map((g) => [
          g.id, 'vulnerable OpenSSL (ML-KEM)', g.readers, percent(g.traffic_share), 'upgrade OpenSSL',
        ]),
        ...summary.unknown.map((g) => [
          g.id, 'key exchange unknown', g.readers, percent(g.traffic_share), 'check the gateway',
        ]),
        ...summary.offline.map((g) => [
          g.id, 'offline, not measured', g.readers, percent(g.traffic_share), 'reconnect',
        ]),
      ];
      return [
        el('div', { className: 'score' },
          el('span', { className: 'score-value', text: percent(summary.readiness) }),
          el('span', { text: 'PQC traffic readiness' }),
          el('progress', { max: 1, value: summary.readiness ?? 0 }),
          el('span', { className: 'hint', text: `${trafficNote}Gateway coverage is ${percent(summary.gateway_coverage)} `
            + `(${gateways.hybrid} of ${plural(gateways.connected, 'connected gateway')} on patched hybrid links).` })),
        el('h3', { text: 'Blocking readiness' }),
        blockers.length
          ? table(
            ['Gateway', 'Why', 'Readers behind it', 'Traffic share (last hour)', 'Next step'],
            blockers,
          )
          : el('p', { text: 'Nothing: every connected gateway is ready.' }),
      ];
    },
    concerns: {
      addressed: [
        'Traffic-weighted PQC readiness for the last hour, with gateway coverage shown separately.',
        'What is blocking readiness: each classical, unknown or offline gateway, its traffic share, and the readers behind it.',
      ],
      notYet: [
        'A migration trend or completion forecast; the Logs tab provides connection records, not a trend.',
      ],
      wont: [
        'Keeping classical fallback until the 2028 replacements: a policy decision that conflicts with the '
          + 'security officer\'s position. The dashboard shows the exposure it leaves, it does not decide.',
      ],
    },
  },

  security: {
    title: 'Security officer',
    question: 'Which connections are still quantum-vulnerable, and how serious is that?',
    draw(summary, devices) {
      const { gateways } = summary;
      // Weakened: hybrid, but on a vulnerable OpenSSL at either end (SCRUM-51).
      const exposed = gateways.classical + gateways.weakened + gateways.unknown;
      const cut = summary.hybrid_only_disconnects;
      const deviceRow = (id) => devices?.devices.find((d) => d.type === 'gateway' && d.id === id)
        ?? { openssl: null, openssl_vulnerable: null };
      const headline = exposed ? (summary.status === 'red' ? 'red' : 'amber') : 'green';
      return [
        el('div', { className: `headline ${headline}` },
          statusBadge(headline,
            exposed ? `Exposed: ${plural(exposed, 'connection')}` : 'No quantum-vulnerable connections'),
          el('p', { text: summary.non_pqc_traffic_share === null
            ? 'No access events in the last hour; traffic readiness is unavailable.'
            : summary.non_pqc_traffic_share === 0
              ? 'All access events in the last hour used hybrid key exchange with patched OpenSSL at both ends.'
              : `${percent(summary.non_pqc_traffic_share)} of access events in the last hour `
                + 'lacked confirmed hybrid key exchange with patched OpenSSL at both ends.' })),
        el('h3', { text: 'Quantum-vulnerable connections' }),
        exposed
          ? table(['Gateway', 'Key exchange', 'Why', 'Readers behind it', 'Share of recent traffic'], [
            ...summary.classical.map((g) => [
              g.id, g.key_exchange, 'classical key exchange', g.readers, percent(g.traffic_share),
            ]),
            ...summary.weakened.map((g) => [
              g.id, g.key_exchange, { text: weakenedReason(deviceRow(g.id), summary.cloud), className: 'warn',
                title: deviceRow(g.id).openssl_advisory ?? summary.cloud?.openssl_advisory ?? '' },
              g.readers, percent(g.traffic_share),
            ]),
            ...summary.unknown.map((g) => [
              g.id, 'unknown', 'key exchange unknown', g.readers, percent(g.traffic_share),
            ]),
          ])
          : el('p', { text: 'None.' }),
        el('h3', { text: 'If classical fallback is turned off' }),
        el('p', { text: cut.gateways
          ? `Switching the cloud to hybrid-only would disconnect ${plural(cut.gateways, 'gateway')} `
            + `and lock ${plural(cut.readers, 'door')} until they are upgraded.`
          : 'Switching the cloud to hybrid-only would disconnect no gateway.' }),
        ...(gateways.weakened ? [el('p', { className: 'hint', text: `It would not fix the ${plural(gateways.weakened,
          'weakened gateway')}: they negotiate hybrid key exchange, so they stay connected until OpenSSL is `
          + 'upgraded.' })] : []),
        ...(summary.offline.length ? [
          el('h3', { text: 'Offline gateways (not monitored)' }),
          table(['Gateway', 'Readers behind it'], summary.offline.map((g) => [g.id, g.readers])),
        ] : []),
        ...deviceStatus(devices, new Set(summary.weakened.map((g) => g.id))),
      ];
    },
    concerns: {
      addressed: [
        'Which connections are still quantum-vulnerable, with the readers behind them and their share of traffic.',
        'Hybrid connections weakened by a vulnerable OpenSSL at either end (e.g. the old 3.5.7) count as '
          + 'quantum-vulnerable, with the OpenSSL version as the reason; the updated 3.5.9 is patched.',
        'No "green" while any classical or weakened connection remains.',
        'What turning off classical fallback would disconnect, and that it would not fix a vulnerable OpenSSL.',
        'Current and past gateway sessions, with their addresses and key exchanges, in the Logs tab.',
        'A list of the encryption library (OpenSSL) versions in use, and which devices and the cloud run each.',
        'The encryption status of every device and link: TLS version, cipher, key exchange, and the '
          + "current OpenSSL version of each device and of the cloud.",
      ],
      notYet: [
        'Automatic alerts on downgrade attempts; the connection history makes changes visible but does not '
          + 'raise an alarm.',
        'Verified library versions: each device reports its own OpenSSL version and the cloud takes it on '
          + 'trust, like device IDs.',
      ],
      wont: [
        'Disabling classical fallback on all connections this quarter: a policy decision that conflicts with the '
          + 'migration plan and the no-outage goal. The dashboard shows its cost, it does not enforce it.',
      ],
    },
  },
};

// '#stakeholders/cio' -> {tab: 'stakeholders', view: 'cio'}; '#logs' -> logs.
function route() {
  const [tab, view] = window.location.hash.slice(1).split('/');
  return {
    tab: ['stakeholders', 'logs'].includes(tab) ? tab : 'operations',
    view: VIEWS[view] ? view : DEFAULT_VIEW,
  };
}

let latestSummary = null;
let latestDevices = null;

function drawView() {
  const { tab, view } = route();
  for (const link of document.querySelectorAll('[data-tab]')) {
    link.classList.toggle('active', link.dataset.tab === tab);
  }
  for (const link of document.querySelectorAll('[data-view]')) {
    link.classList.toggle('active', link.dataset.view === view);
  }
  $('tab-operations').hidden = tab !== 'operations';
  $('tab-stakeholders').hidden = tab !== 'stakeholders';
  $('tab-logs').hidden = tab !== 'logs';
  if (tab !== 'stakeholders' || !latestSummary) return;

  const spec = VIEWS[view];
  redraw('stakeholder-view', [view, latestSummary, latestDevices], () => {
    // Traffic shares change with almost every refresh, so the view is redrawn
    // often: keep each table's scroll position, as the Operations tab does.
    const scrolled = [...$('view').querySelectorAll('.scroll')]
      .map((box) => [box.scrollLeft, box.scrollTop]);
    $('view').replaceChildren(
      el('p', { className: 'question', text: `“${spec.question}”` }),
      ...spec.draw(latestSummary, latestDevices),
      concerns(spec.concerns),
    );
    $('view').querySelectorAll('.scroll').forEach((box, index) => {
      if (scrolled[index]) [box.scrollLeft, box.scrollTop] = scrolled[index];
    });
  });
}

async function refreshSummary() {
  if (route().tab !== 'stakeholders') return;
  try {
    [latestSummary, latestDevices] = await Promise.all([
      getJSON('/api/summary'), getJSON('/api/devices'),
    ]);
    drawView();
  } catch (error) {
    $('status').textContent = `Update failed: ${error.message}`;
  }
}

window.addEventListener('hashchange', () => {
  drawView();
  refreshSummary();
});
drawView();
refreshSummary();
setInterval(refreshSummary, SUMMARY_MS);
