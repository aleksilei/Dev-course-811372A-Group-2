"""The post-quantum migration at a glance, for the panel's stakeholder views.

summarize() is a pure function of what the cloud knows right now: the
connected gateways, the gateways and readers in the database, and the recent
access events. It holds the readiness score (SCRUM-11) and the status rules.
"""

import re
from collections import Counter

# How many of the newest access events count as "recent traffic".
RECENT_EVENTS = 500


def _natural(gateway_id: str) -> list:
    """Sort key that puts gw-s9 before gw-s10."""
    return [
        int(part) if part.isdigit() else part for part in re.split(r'(\d+)', gateway_id)
    ]


def summarize(
    connected: list[dict],
    known_ids: list[str],
    readers: list[dict],
    events: list[dict],
) -> dict:
    """Readiness, status and risks.

    connected: GatewayHub.connected() rows (id, post_quantum, key_exchange, ...)
    known_ids: gateway IDs in the database
    readers: Database.readers() rows (id, gateway_id, zone_name)
    events: recent Database.events() rows (gateway_id, ...)
    """
    online = {gateway['id']: gateway for gateway in connected}
    known = sorted(set(known_ids) | set(online), key=_natural)
    readers_at = Counter(reader['gateway_id'] for reader in readers)
    traffic_at = Counter(event['gateway_id'] for event in events)

    def detail(gateway_id: str) -> dict:
        gateway = online.get(gateway_id, {})
        return {
            'id': gateway_id,
            'key_exchange': gateway.get('key_exchange'),
            'readers': readers_at[gateway_id],
            'traffic_share': _share(traffic_at[gateway_id], len(events)),
        }

    hybrid = [g for g in online if online[g].get('post_quantum') is True]
    classical = sorted(
        (g for g in online if online[g].get('post_quantum') is False), key=_natural
    )
    unknown = sorted(
        (g for g in online if online[g].get('post_quantum') is None), key=_natural
    )
    offline = [g for g in known if g not in online]

    classical_details = [detail(g) for g in classical]
    summary = {
        'readiness': _share(len(hybrid), len(online)),
        'gateways': {
            'known': len(known),
            'connected': len(online),
            'hybrid': len(hybrid),
            'classical': len(classical),
            'unknown': len(unknown),
            'offline': len(offline),
        },
        'readers': len(readers),
        'classical': classical_details,
        'unknown': [detail(g) for g in unknown],
        'offline': [detail(g) for g in offline],
        'classical_traffic_share': _share(
            sum(traffic_at[g] for g in classical), len(events)
        ),
        # What switching the cloud to KEY_EXCHANGE=hybrid-only would cut off.
        'hybrid_only_disconnects': {
            'gateways': len(classical),
            'readers': sum(readers_at[g] for g in classical),
        },
        'recent_events': len(events),
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
        traffic = f'; they carry {share:.0%} of recent door traffic' if share else ''
        risks.append(
            {
                'severity': 'high' if summary['status'] == 'red' else 'medium',
                'title': f'{gateways["classical"]} of {_plural(gateways["connected"], "gateway")}'
                f' {"uses" if gateways["classical"] == 1 else "use"} classical encryption',
                'detail': 'Their traffic could be recorded now and decrypted by a future '
                f'quantum computer{traffic}.',
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
