import asyncio
import random

from lib import tls
from lib.config import env, setup_logging
from reader.scanner import GatewayClient, scan

DEFAULT_KEYS = 'key-alice,key-bob,key-carol,key-mallory'


async def run():
    zone = env('ZONE')
    keys = env('KEYS', DEFAULT_KEYS).split(',')
    interval = float(env('SCAN_INTERVAL', '5'))
    client = GatewayClient(
        f'wss://{env("GATEWAY")}',
        env('READER_ID'),
        tls.client_context(env('TLS_CA', '/certs/ca.pem'), tls.READER_GATEWAY),
    )
    while True:
        await scan(client, random.choice(keys), zone)
        await asyncio.sleep(interval)


def main():
    setup_logging()
    asyncio.run(run())


if __name__ == '__main__':
    main()
