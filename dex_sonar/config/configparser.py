from datetime import timedelta
from os import path, getcwd

from configparser import ConfigParser


class Config(ConfigParser):
    def read(self, file_name, directory_path='configs', **kwargs):
        super().read(path.join(getcwd(), directory_path, file_name))

    def getint(self, section, option, default: int = None, **kwargs) -> int | None:
        return super().getint(section, option, **kwargs) if self.get(section, option, **kwargs) else default

    def getfloat(self, section, option, default: float = None, **kwargs) -> float | None:
        return super().getfloat(section, option, **kwargs) if self.get(section, option, **kwargs) else default

    def get_normalized_percent(self, section, option, default: timedelta = None, **kwargs) -> float | None:
        return super().getfloat(section, option, **kwargs) / 100 if self.get(section, option, **kwargs) else default

    def get_timedelta_from_seconds(self, section, option, default: timedelta = None, **kwargs) -> timedelta | None:
        return timedelta(seconds=self.getint(section, option, **kwargs)) if self.get(section, option, **kwargs) else default

    def get_timedelta_from_minutes(self, section, option, default: timedelta = None, **kwargs) -> timedelta | None:
        return timedelta(minutes=self.getint(section, option, **kwargs)) if self.get(section, option, **kwargs) else default

    def get_timedelta_from_hours(self, section, option, default: timedelta = None, **kwargs) -> timedelta | None:
        return timedelta(hours=self.getint(section, option, **kwargs)) if self.get(section, option, **kwargs) else default
