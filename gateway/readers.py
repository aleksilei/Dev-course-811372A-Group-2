from gateway.cloud_link import CloudLink
from lib.hub import REPORTED_FIELDS, Hub

# What the cloud is told about each connected reader.
REPORTED = REPORTED_FIELDS


class ReaderHub(Hub):
    """Relays each connected reader's requests to the cloud; no local logic."""

    id_header = 'Reader-Id'

    def __init__(self, cloud: CloudLink) -> None:
        super().__init__()
        self.cloud = cloud
        # Report the empty list too: the cloud then knows that no reader is
        # connected, rather than not knowing.
        self.changed()

    def changed(self) -> None:
        self.cloud.report_readers(
            [
                {field: reader[field] for field in REPORTED}
                for reader in self.connected()
            ]
        )

    async def respond(self, request: dict, client_id: str) -> dict:
        reply = await self.cloud.request(request)
        # Fail closed: anything but an explicit pass is a fail.
        return {'result': 'pass' if reply.get('result') == 'pass' else 'fail'}
