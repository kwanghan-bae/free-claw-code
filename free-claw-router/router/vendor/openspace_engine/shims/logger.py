"""Replace openspace.utils.logging.Logger with stdlib logging."""
import logging


class Logger:
    def __init__(self, name: str = "openspace_engine"):
        self._log = logging.getLogger(name)

    def info(self, msg, *a, **kw): self._log.info(msg, *a)
    def debug(self, msg, *a, **kw): self._log.debug(msg, *a)
    def warning(self, msg, *a, **kw): self._log.warning(msg, *a)
    def error(self, msg, *a, **kw): self._log.error(msg, *a)
    def success(self, msg, *a, **kw): self._log.info(msg, *a)

    @classmethod
    def get_logger(cls, name: str = "openspace_engine") -> "Logger":
        return cls(name)
