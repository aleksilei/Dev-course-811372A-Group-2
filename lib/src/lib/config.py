import logging
import os


class ConfigError(Exception):
    pass


def env(name: str, default: str | None = None) -> str:
    """Read an environment variable; without a default the variable is required."""
    value = os.environ.get(name, default)
    if value is None:
        raise ConfigError(f'Missing required environment variable {name}')
    return value


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    )
