import logging
import sys

from pythonjsonlogger import jsonlogger

from app.config import settings


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(settings.LOG_LEVEL)
    root.addHandler(handler)
