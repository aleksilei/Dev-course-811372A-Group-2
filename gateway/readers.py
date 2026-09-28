from gateway.cloud_link import CloudLink
from lib.hub import Hub


class ReaderHub(Hub):
    """Relays each connected reader's requests to the cloud; no local logic."""

    id_header = 'Reader-Id'

    def __init__(self, cloud: CloudLink) -> None:
        super().__init__()
        self.cloud = cloud

    async def respond(self, request: dict, client_id: str) -> dict:
        reply = await self.cloud.request(request)
        # Fail closed: anything but an explicit pass is a fail.
        return {'result': 'pass' if reply.get('result') == 'pass' else 'fail'}
