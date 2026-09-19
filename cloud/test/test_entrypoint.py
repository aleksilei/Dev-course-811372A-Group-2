from lib.config import Config


def test_config_can_be_instantiated():
    config = Config()

    assert config is not None
