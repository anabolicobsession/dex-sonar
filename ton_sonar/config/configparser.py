from os import path

from configparser import ConfigParser


class Config(ConfigParser):
    def read(self, file_name, **kwargs):
        super().read(path.join(path.dirname(path.abspath(__file__)), file_name), **kwargs)

    def getint(self, section, option, **kwargs) -> int | None:
        return super().getint(section, option, **kwargs) if self.get(section, option, **kwargs) else None

    def getfloat(self, section, option, **kwargs) -> float | None:
        return super().getfloat(section, option, **kwargs) if self.get(section, option, **kwargs) else None
