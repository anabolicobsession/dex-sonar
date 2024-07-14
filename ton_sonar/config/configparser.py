import os
from configparser import ConfigParser


# should be at the same directory
_CONFIG_FILENAME = 'config.ini'


class Config(ConfigParser):
    def getint(self, section, option, **kwargs) -> int | None:
        return super().getint(section, option, **kwargs) if self.get(section, option, **kwargs) else None

    def getfloat(self, section, option, **kwargs) -> float | None:
        return super().getfloat(section, option, **kwargs) if self.get(section, option, **kwargs) else None


config = Config()
config.read(os.path.join(os.path.dirname(os.path.abspath(__file__)), _CONFIG_FILENAME))
