'use strict';

// Tabs (#operations, #stakeholders/<view>) and the stakeholder views, drawn
// from /api/summary. Loaded after app.js, whose $() and getJSON() it uses.

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

function table(headers, rows) {
  const body = el('tbody');
  for (const row of rows) body.append(el('tr', {}, ...row.map((cell) => el('td', { text: cell }))));
  return el('div', { className: 'scroll' }, el('table', {},
    el('thead', {}, el('tr', {}, ...headers.map((header) => el('th', { text: header })))),
    body));
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
      const blockers = [
        ...summary.classical.map((g) => [g.id, 'classical key exchange', g.readers, 'upgrade or replace']),
        ...summary.unknown.map((g) => [g.id, 'key exchange unknown', g.readers, 'check the gateway']),
        ...summary.offline.map((g) => [g.id, 'offline, not measured', g.readers, 'reconnect']),
      ];
      return [
        el('div', { className: 'score' },
          el('span', { className: 'score-value', text: percent(summary.readiness) }),
          el('span', { text: 'PQC readiness' }),
          el('progress', { max: 1, value: summary.readiness ?? 0 }),
          el('span', { className: 'hint', text: `${gateways.hybrid} of ${plural(gateways.connected, 'connected gateway')} `
            + `on post-quantum hybrid key exchange${gateways.offline ? `; ${gateways.offline} offline, not counted` : ''}.` })),
        el('h3', { text: 'Blocking readiness' }),
        blockers.length
          ? table(['Gateway', 'Why', 'Readers behind it', 'Next step'], blockers)
          : el('p', { text: 'Nothing: every connected gateway is ready.' }),
      ];
    },
    concerns: {
      addressed: [
        'A single readiness score to report upwards: the share of connected gateways on post-quantum hybrid.',
        'What is blocking readiness: each classical, unknown or offline gateway and the readers behind it.',
      ],
      notYet: [
        'Progress over time, and whether the migration will finish on time: needs the connection history (SCRUM-33).',
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
    draw(summary) {
      const { gateways } = summary;
      const exposed = gateways.classical + gateways.unknown;
      const cut = summary.hybrid_only_disconnects;
      return [
        el('div', { className: `headline ${exposed ? (summary.status === 'red' ? 'red' : 'amber') : 'green'}` },
          statusBadge(exposed ? (summary.status === 'red' ? 'red' : 'amber') : 'green',
            exposed ? `Exposed: ${plural(exposed, 'connection')}` : 'No classical connections'),
          el('p', { text: exposed
            ? `${percent(summary.classical_traffic_share)} of the last ${summary.recent_events} access events `
              + 'went over classical key exchange and could be harvested now and decrypted later.'
            : 'Every connected gateway negotiated post-quantum hybrid key exchange.' })),
        el('h3', { text: 'Quantum-vulnerable connections' }),
        exposed
          ? table(['Gateway', 'Key exchange', 'Readers behind it', 'Share of recent traffic'], [
            ...summary.classical.map((g) => [g.id, g.key_exchange, g.readers, percent(g.traffic_share)]),
            ...summary.unknown.map((g) => [g.id, 'unknown', g.readers, percent(g.traffic_share)]),
          ])
          : el('p', { text: 'None.' }),
        el('h3', { text: 'If classical fallback is turned off' }),
        el('p', { text: cut.gateways
          ? `Switching the cloud to hybrid-only would disconnect ${plural(cut.gateways, 'gateway')} `
            + `and lock ${plural(cut.readers, 'door')} until they are upgraded.`
          : 'Switching the cloud to hybrid-only would disconnect no gateway.' }),
        ...(summary.offline.length ? [
          el('h3', { text: 'Offline gateways (not monitored)' }),
          table(['Gateway', 'Readers behind it'], summary.offline.map((g) => [g.id, g.readers])),
        ] : []),
      ];
    },
    concerns: {
      addressed: [
        'Which connections are still quantum-vulnerable, with the readers behind them and their share of traffic.',
        'No "green" while any classical connection remains.',
        'What turning off classical fallback would disconnect.',
      ],
      notYet: [
        'Alerts on downgrade attempts (a gateway that used hybrid now connecting classically): needs the '
          + 'connection history (SCRUM-33).',
        'Past connections: the Logs tab (SCRUM-34).',
      ],
      wont: [
        'Disabling classical fallback on all connections this quarter: a policy decision that conflicts with the '
          + 'migration plan and the no-outage goal. The dashboard shows its cost, it does not enforce it.',
      ],
    },
  },
};

// '#stakeholders/cio' -> {tab: 'stakeholders', view: 'cio'}
function route() {
  const [tab, view] = window.location.hash.slice(1).split('/');
  return {
    tab: tab === 'stakeholders' ? 'stakeholders' : 'operations',
    view: VIEWS[view] ? view : DEFAULT_VIEW,
  };
}

let latestSummary = null;

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
  if (tab !== 'stakeholders' || !latestSummary) return;

  const spec = VIEWS[view];
  redraw('stakeholder-view', [view, latestSummary], () => $('view').replaceChildren(
    el('p', { className: 'question', text: `“${spec.question}”` }),
    ...spec.draw(latestSummary),
    concerns(spec.concerns),
  ));
}

async function refreshSummary() {
  if (route().tab !== 'stakeholders') return;
  try {
    latestSummary = await getJSON('/api/summary');
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
