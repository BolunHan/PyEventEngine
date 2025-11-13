import logging

from ..base import LOGGER

__all__ = ['set_logger', 'LOG_LEVEL_EVENT', 'Topic', 'RegularTopic', 'PatternTopic', 'EventHook', 'EventEngine', 'LOGGER']
DEBUG = False
LOG_LEVEL = logging.INFO
LOG_LEVEL_EVENT = LOG_LEVEL - 5


def set_logger(logger: logging.Logger):
    global LOGGER
    LOGGER = logger

    _event.LOGGER = LOGGER.getChild('Event')


from ._topic import Topic, RegularTopic, PatternTopic
from ._event import EventHook, EventEngine
