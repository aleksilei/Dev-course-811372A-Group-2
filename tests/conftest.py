import asyncio
import inspect
from types import SimpleNamespace

import pytest

from cloud.db import Database
from lib.certs import generate


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem):
    """Run `async def` tests with asyncio.run() (instead of a plugin)."""
    test = pyfuncitem.obj
    if not inspect.iscoroutinefunction(test):
        return None
    names = inspect.signature(test).parameters
    asyncio.run(test(**{name: pyfuncitem.funcargs[name] for name in names}))
    return True


@pytest.fixture(scope='session')
def certs(tmp_path_factory):
    """A dev CA and one server certificate valid for localhost."""
    out = tmp_path_factory.mktemp('certs')
    generate(out, {'server': 'DNS:localhost,IP:127.0.0.1'})
    return SimpleNamespace(
        ca=str(out / 'ca.pem'),
        cert=str(out / 'server.pem'),
        key=str(out / 'server.key'),
    )


@pytest.fixture
def db(tmp_path):
    """A fresh database holding the example data from cloud/seed.sql."""
    database = Database(tmp_path / 'master.db')
    database.init()
    return database


@pytest.fixture
def wait_until():
    """`await wait_until(predicate)` polls until the predicate holds."""

    async def wait(predicate, timeout=5.0):
        async with asyncio.timeout(timeout):
            while not predicate():
                await asyncio.sleep(0.01)

    return wait
