import logging

from cbase.backports.telemetrics import (
    ColoredFormatter,
    DuplicateWarningFilter,
    LOG_LEVEL,
    get_logger as _get_logger,
)

LOG_LEVEL_EVENT = LOG_LEVEL - 5


def get_logger(**kwargs) -> logging.Logger:
    """Return the process-wide singleton EventEngine logger.

    First call configures the logger via PyCyBase's telemetrics; subsequent
    calls return the same cached instance.
    """
    return _get_logger(
        name='EventEngine',
        level=kwargs.get('level', LOG_LEVEL),
        stream_io=kwargs.get('stream_io', None),
        formatter=kwargs.get('formatter', None),
    )


LOGGER = get_logger()

__all__ = [
    'ColoredFormatter',
    'DuplicateWarningFilter',
    'LOG_LEVEL',
    'LOG_LEVEL_EVENT',
    'LOGGER',
    'get_logger',
]
