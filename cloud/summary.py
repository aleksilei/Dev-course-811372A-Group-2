"""The post-quantum migration at a glance, for the panel's stakeholder views.

summarize() is a pure function of what the cloud knows right now: the
connected gateways, the gateways and readers in the database, and the recent
access traffic. It holds the readiness scores (SCRUM-11) and the status rules.
"""

import re
from collections import Counter
from datetime import timedelta

from lib.tls import is_post_quantum

# The rolling traffic window used by the migration and security scores.
TRAFFIC_WINDOW = timedelta(hours=1)


def _natural(gateway_id: str) -> list:
    """Sort key that puts gw-s9 before gw-s10."""
    return [
        int(part) if part.isdigit() else part for part in re.split(r'(\d+)', gateway_id)
    ]


def _gateway_groups(online: dict[str, dict], known: list[str]) -> dict[str, list[str]]:
    """Classify connected gateways and identify those known but offline."""
    return {
        'hybrid': [g for g in online if online[g].get('post_quantum') is True],
        'classical': sorted(
            (g for g in online if online[g].get('post_quantum') is False), key=_natural
        ),
        'unknown': sorted(
            (g for g in online if online[g].get('post_quantum') is None), key=_natural
        ),
        'offline': [g for g in known if g not in online],
    }


def _traffic_summary(events: list[dict]) -> dict:
    """Use recorded encryption at event time; unknown events count as non-PQC."""
    counts = Counter()
    for event in events:
        counts[is_post_quantum(event.get('key_exchange'))] += event.get('count', 1)
    total = sum(counts.values())
    return {
        'total': total,
        'readiness': _share(counts[True], total),
        'non_pqc_share': _share(counts[False] + counts[None], total),
        'classical_share': _share(counts[False], total),
    }


def summarize(
    connected: list[dict],
    known_ids: list[str],
    readers: list[dict],
    events: list[dict],
    traffic_counts: list[dict] | None = None,
) -> dict:
    """Traffic readiness, gateway coverage, status and risks.

    connected: GatewayHub.connected() rows (id, post_quantum, key_exchange, ...)
    known_ids: gateway IDs in the database
    readers: Database.readers() rows (id, gateway_id, zone_name)
    events: access events (gateway_id, key_exchange), unless traffic_counts is supplied
    traffic_counts: rows (gateway_id, key_exchange, count) within the traffic window
    """
    online = {gateway['id']: gateway for gateway in connected}
    known = sorted(set(known_ids) | set(online), key=_natural)
    readers_at = Counter(reader['gateway_id'] for reader in readers)
    window_events = traffic_counts if traffic_counts is not None else events
    traffic_at = Counter()
    for event in window_events:
        traffic_at[event['gateway_id']] += event.get('count', 1)
    groups = _gateway_groups(online, known)
    traffic = _traffic_summary(window_events)

    def detail(gateway_id: str) -> dict:
        gateway = online.get(gateway_id, {})
        return {
            'id': gateway_id,
            'key_exchange': gateway.get('key_exchange'),
            'readers': readers_at[gateway_id],
            'traffic_share': _share(traffic_at[gateway_id], traffic['total']),
        }

    summary = {
        'readiness': traffic['readiness'],
        'gateway_coverage': _share(len(groups['hybrid']), len(online)),
        'gateways': {
            'known': len(known),
            'connected': len(online),
            'hybrid': len(groups['hybrid']),
            'classical': len(groups['classical']),
            'unknown': len(groups['unknown']),
            'offline': len(groups['offline']),
        },
        'readers': len(readers),
        'classical': [detail(g) for g in groups['classical']],
        'unknown': [detail(g) for g in groups['unknown']],
        'offline': [detail(g) for g in groups['offline']],
        'classical_traffic_share': traffic['classical_share'],
        'non_pqc_traffic_share': traffic['non_pqc_share'],
        # What switching the cloud to KEY_EXCHANGE=hybrid-only would cut off.
        'hybrid_only_disconnects': {
            'gateways': len(groups['classical']),
            'readers': sum(readers_at[g] for g in groups['classical']),
        },
        'recent_events': traffic['total'],
    }
    summary['status'] = _status(summary['gateways'])
    summary['risks'] = _risks(summary)
    return summary


def _share(part: int, whole: int) -> float | None:
    return round(part / whole, 3) if whole else None


def _status(gateways: dict) -> str:
    """green: every gateway connected and on hybrid; red: a gateway offline or
    over half of the connected ones classical; amber otherwise."""
    connected = gateways['connected']
    if gateways['offline'] or (connected and gateways['classical'] / connected > 0.5):
        return 'red'
    if connected and gateways['hybrid'] == connected:
        return 'green'
    return 'amber'


def _plural(count: int, word: str) -> str:
    return f'{count} {word}{"" if count == 1 else "s"}'


def _risks(summary: dict) -> list[dict]:
    """Risks in plain language, most severe first."""
    gateways, risks = summary['gateways'], []
    if summary['offline']:
        doors = sum(g['readers'] for g in summary['offline'])
        risks.append(
            {
                'severity': 'high',
                'title': f'{_plural(gateways["offline"], "site gateway")} offline',
                'detail': f'{_plural(doors, "door")} behind them cannot be checked, '
                'so they stay locked until the gateway is back.',
                'gateways': [g['id'] for g in summary['offline']],
            }
        )
    if summary['classical']:
        share = summary['classical_traffic_share']
        traffic = (
            f" Across all gateways, {share:.0%} of last hour's door traffic "
            'was recorded with classical key exchange.'
            if share
            else ''
        )
        risks.append(
            {
                'severity': 'high' if summary['status'] == 'red' else 'medium',
                'title': f'{gateways["classical"]} of {_plural(gateways["connected"], "gateway")}'
                f' {"uses" if gateways["classical"] == 1 else "use"} classical encryption',
                'detail': 'Their traffic could be recorded now and decrypted by a future '
                f'quantum computer.{traffic}',
                'gateways': [g['id'] for g in summary['classical']],
            }
        )
        cut = summary['hybrid_only_disconnects']
        risks.append(
            {
                'severity': 'medium',
                'title': 'Turning off classical fallback would cut off '
                f'{_plural(cut["gateways"], "gateway")}',
                'detail': f'{_plural(cut["readers"], "door")} would stay locked until '
                'those gateways are upgraded or replaced.',
                'gateways': [g['id'] for g in summary['classical']],
            }
        )
    if summary['unknown']:
        risks.append(
            {
                'severity': 'low',
                'title': f'{_plural(gateways["unknown"], "gateway")} with unknown encryption',
                'detail': 'The cloud could not tell which key exchange they negotiated.',
                'gateways': [g['id'] for g in summary['unknown']],
            }
        )
    return risks
