from os import path, getcwd

from configparser import ConfigParser


class Config(ConfigParser):
    def read(self, file_name, directory_path='configs', **kwargs):
        super().read(path.join(getcwd(), directory_path, file_name))

    def getint(self, section, option, **kwargs) -> int | None:
        return super().getint(section, option, **kwargs) if self.get(section, option, **kwargs) else None

    def getfloat(self, section, option, **kwargs) -> float | None:
        return super().getfloat(section, option, **kwargs) if self.get(section, option, **kwargs) else None
