import asyncio

from websockets.asyncio.server import serve

from gateway.cloud_link import CloudLink
from gateway.readers import ReaderHub
from lib import tls
from lib.config import env, setup_logging


async def run():
    ca = env('TLS_CA', '/certs/ca.pem')
    cloud = CloudLink(
        f'wss://{env("CLOUD")}', env('ID'), tls.client_context(ca, tls.GATEWAY_CLOUD)
    )
    readers = ReaderHub(cloud)
    context = tls.server_context(
        env('TLS_CERT', '/certs/server.pem'),
        env('TLS_KEY', '/certs/server.key'),
        tls.READER_GATEWAY,
    )
    port = int(env('PORT', '8765'))
    async with serve(readers.handle, '0.0.0.0', port, ssl=context) as server:
        await asyncio.gather(cloud.run(), server.serve_forever())


def main():
    setup_logging()
    asyncio.run(run())


if __name__ == '__main__':
    main()
