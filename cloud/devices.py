"""Every device and the encryption of its links toward the cloud (SCRUM-18).

devices() is a pure function of what the cloud knows right now: the connected
gateways with the readers each one reports, the gateways and readers in the
database, and the panel request's own connection. A device's status is its weakest
link: a reader's traffic crosses its own reader -> gateway link and its
gateway's link to the cloud. Anything the cloud can't confirm is never shown
as encrypted.
"""

from collections import Counter

from cloud.summary import _natural
from lib import tls

STATUSES = ('post-quantum', 'classical', 'unknown', 'offline')

GATEWAY_LINK = 'gateway → cloud'
READER_LINK = 'reader → gateway'
PANEL_LINK = 'browser → control panel'


def _link(name: str, details: dict) -> dict:
    """One link: a name and the TLS details a Hub row or a reader report has."""
    group = details.get('key_exchange')
    return {
        'name': name,
        'tls_version': details.get('tls_version'),
        'cipher': details.get('cipher'),
        'key_exchange': group,
        'post_quantum': tls.is_post_quantum(group),
    }


def _weakest(links: list[dict]) -> str:
    """Classical if any link is, unknown if any can't be told, else post-quantum."""
    flags = [link['post_quantum'] for link in links]
    if False in flags:
        return 'classical'
    if None in flags or not flags:
        return 'unknown'
    return 'post-quantum'


def devices(
    connected: list[dict],
    known_gateway_ids: list[str],
    readers: list[dict],
    panel_connection: object = None,
) -> dict:
    """Every gateway and reader with the encryption of its links.

    connected: GatewayHub.connected() rows, each with its reported `readers`
    known_gateway_ids: gateway IDs in the database
    readers: Database.readers() rows (id, gateway_id, zone_name)
    panel_connection: the SSLSocket of the panel request asking, if any
    """
    online = {gateway['id']: gateway for gateway in connected}
    known = set(known_gateway_ids) | {
        reader['gateway_id'] for reader in readers if reader.get('gateway_id')
    }
    rows = _gateway_rows(online, known) + _reader_rows(online, readers)

    counts = {
        kind: Counter({status: 0 for status in STATUSES})
        for kind in ('gateway', 'reader')
    }
    for row in rows:
        counts[row['type']][row['status']] += 1
    return {
        'statuses': list(STATUSES),
        'counts': {kind: dict(counter) for kind, counter in counts.items()},
        'devices': rows,
        'panel': _link(PANEL_LINK, tls.link_details(panel_connection))
        if panel_connection is not None
        else None,
    }


def _gateway_rows(online: dict[str, dict], known: set[str]) -> list[dict]:
    rows = []
    for gateway_id in sorted(known | set(online), key=_natural):
        gateway = online.get(gateway_id)
        links = [_link(GATEWAY_LINK, gateway)] if gateway else []
        rows.append(
            {
                'id': gateway_id,
                'type': 'gateway',
                'gateway': None,
                'registered': gateway_id in known,
                'state': 'connected' if gateway else 'offline',
                'status': _status(gateway_id in known, gateway is not None, links),
                'links': links,
            }
        )
    return rows


def _reader_rows(online: dict[str, dict], readers: list[dict]) -> list[dict]:
    registered = {reader['id']: reader for reader in readers}
    # Reader ID -> (the gateway it is connected through, its reported link).
    reported = {
        reader['id']: (gateway_id, reader)
        for gateway_id, gateway in online.items()
        for reader in gateway.get('readers') or []
    }

    def gateway_of(reader_id: str) -> str | None:
        if reader_id in reported:
            return reported[reader_id][0]
        return registered[reader_id].get('gateway_id')

    rows = []
    for reader_id in sorted(
        set(registered) | set(reported),
        key=lambda r: (_natural(gateway_of(r) or ''), _natural(r)),
    ):
        links = []
        if reader_id in reported:
            via, link = reported[reader_id]
            links = [_link(READER_LINK, link), _link(GATEWAY_LINK, online[via])]
            state = 'connected'
            status = _status(reader_id in registered, True, links)
        elif (online.get(gateway_of(reader_id)) or {}).get('readers') is not None:
            # Only a gateway that reports its readers can say one isn't there.
            state, status = 'not connected', 'offline'
        else:
            state, status = 'unknown', 'unknown'
        rows.append(
            {
                'id': reader_id,
                'type': 'reader',
                'gateway': gateway_of(reader_id),
                'registered': reader_id in registered,
                'state': state,
                'status': status,
                'links': links,
            }
        )
    return rows


def _status(registered: bool, connected: bool, links: list[dict]) -> str:
    if not connected:
        return 'offline'
    if not registered:
        # Its links are measured, but the device itself is unknown to the cloud.
        return 'unknown'
    return _weakest(links)
