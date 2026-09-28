import asyncio
import ssl
import threading

from websockets.asyncio.server import serve

from cloud.db import Database
from cloud.gateways import GatewayHub
from cloud.panel import PanelServer
from lib import tls
from lib.config import env, setup_logging


async def serve_gateways(gateways: GatewayHub, context: ssl.SSLContext, port: int):
    async with serve(gateways.handle, '0.0.0.0', port, ssl=context) as server:
        await server.serve_forever()


def main():
    setup_logging()
    db = Database(env('DB_PATH', '/data/master.db'))
    db.init()
    cert, key = (
        env('TLS_CERT', '/certs/server.pem'),
        env('TLS_KEY', '/certs/server.key'),
    )
    gateways = GatewayHub(db)

    panel = PanelServer(
        ('0.0.0.0', int(env('PANEL_PORT', '8444'))),
        tls.server_context(cert, key, tls.ADMIN_CLOUD),
        db,
        gateways,
    )
    threading.Thread(target=panel.serve_forever, daemon=True).start()

    asyncio.run(
        serve_gateways(
            gateways,
            tls.server_context(cert, key, tls.GATEWAY_CLOUD),
            int(env('GATEWAY_PORT', '8443')),
        )
    )


if __name__ == '__main__':
    main()
