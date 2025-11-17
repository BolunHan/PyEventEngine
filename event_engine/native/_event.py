"""
DEPRECATED: This module is deprecated and will be removed in a future version.

This was an old implementation that doesn't match the Cython API.
Please use event_engine.native.event instead, which provides a proper
Python fallback implementation that mimics the Cython c_event module.
"""

import warnings
import datetime
import enum
import inspect
import time
import traceback
from collections import deque
from logging import Logger
from threading import Thread, Semaphore
from typing import Iterable, TypedDict, NotRequired, Callable

from . import LOGGER, LOG_LEVEL_EVENT, Topic, DEBUG

warnings.warn(
    "event_engine.native._event is deprecated. Use event_engine.native.event instead.",
    DeprecationWarning,
    stacklevel=2
)

LOGGER = LOGGER.getChild('Event')


class EventDict(TypedDict):
    topic: str
    args: NotRequired[tuple]
    kwargs: NotRequired[dict]


class EventHookBase(object):
    """
    Event object with
    a string topic for event engine to distribute event,
    and a list of handler to process data
    """

    def __init__(self, topic: Topic, logger: Logger = None, max_size: int = None):
        self.topic = topic
        self.logger = LOGGER.getChild(f'EventHook.{topic}') if logger is None else logger
        self.handlers: deque[Callable] = deque(maxlen=max_size)

    def __call__(self, *args, **kwargs):
        self.trigger(topic=self.topic, args=args, kwargs=kwargs)

    def __iadd__(self, handler: Callable):
        self.add_handler(handler)
        return self

    def __isub__(self, handler: Callable):
        self.remove_handler(handler)
        return self

    def trigger(self, topic: Topic, args: tuple = None, kwargs: dict = None):
        if args is None:
            args = ()

        if kwargs is None:
            kwargs = {}

        for handler in self.handlers:
            try:
                try:
                    handler(topic=topic, *args, **kwargs)
                except TypeError as e:
                    if e.__str__().endswith("unexpected keyword argument 'topic'"):
                        handler(*args, **kwargs)
                    else:
                        raise e
            except Exception as _:
                self.logger.error(traceback.format_exc())

    def add_handler(self, handler: Callable):
        if handler in self.handlers:
            LOGGER.warning(f'Handler {handler} already in {self}. This action might cause it to trigger twice.')
        self.handlers.append(handler)

    def remove_handler(self, handler: Callable):
        try:
            self.handlers.remove(handler)
        except ValueError as e:
            self.logger.error(f'Handler {handler} not found in {self}.')


class EventHook(EventHookBase):
    def __init__(self, topic: Topic, logger: Logger = None, max_size: int = None, handler: list[Callable] | Callable | None = None):
        super().__init__(topic=topic, logger=logger, max_size=max_size)
        self.with_topic: deque[bool] = deque()

        if handler is None:
            pass
        elif callable(handler):
            self.add_handler(handler)
        elif isinstance(handler, Iterable):
            for _handler in handler:
                self.add_handler(handler=_handler)
        else:
            raise ValueError(f'Invalid handler {handler}, expect a Callable or a list of Callable.')

    def trigger(self, topic: Topic, args: tuple = None, kwargs: dict = None):
        ts = time.time()
        if args is None:
            args = ()

        if kwargs is None:
            kwargs = {}

        for handler, with_topic in zip(self.handlers, self.with_topic):
            try:
                if with_topic:
                    handler(topic=topic, *args, **kwargs)
                else:
                    handler(*args, **kwargs)
            except Exception as _:
                self.logger.error(traceback.format_exc())

        if DEBUG:
            self.logger.log(LOG_LEVEL_EVENT, f'EventHook {self.topic} tasks triggered {len(self.handlers):,} handlers, complete in {(time.time() - ts) * 1000:.3f}ms.')

    def add_handler(self, handler: Callable, with_topic: bool = None):
        sig = inspect.signature(handler)

        if with_topic is None:
            for param in sig.parameters.values():
                if param.name == 'topic' or param.kind == param.VAR_KEYWORD:
                    with_topic = True
                    break

        super().add_handler(handler=handler)
        self.with_topic.append(with_topic)

    def remove_handler(self, handler: Callable):
        try:
            idx = self.handlers.index(handler)
            self.handlers.__delitem__(idx)
            self.with_topic.__delitem__(idx)
        except ValueError as e:
            pass


class EventEngineBase(object):
    EventHook = EventHook

    def __init__(self, logger: Logger = None, buffer_size: int = 0):
        self.logger = LOGGER.getChild(f'EventEngine') if logger is None else logger
        self._buffer_size = buffer_size
        self._put_lock = Semaphore(self._buffer_size)
        self._get_lock = Semaphore(0)
        self._deque: deque[EventDict] = deque(maxlen=buffer_size if buffer_size else None)
        self._active: bool = False
        self._engine: Thread = None
        self._event_hooks: dict[Topic, EventHook] = {}

        if buffer_size and buffer_size < 8:
            self.logger.info(f'buffer_size={buffer_size} too small. This might cause a dead lock.')

    def _run(self) -> None:
        """
        Get event from queue and then process it.
        """
        while self._active:
            self._get_lock.acquire(blocking=True, timeout=None)

            try:
                event_dict = self._deque.popleft()
            except IndexError as e:
                if not self._active:
                    return
                raise e

            topic = event_dict['topic']
            args = event_dict.get('args', ())
            kwargs = event_dict.get('kwargs', {})
            self._process(topic=topic, *args, **kwargs)

            if self._buffer_size:
                self._put_lock.release()

    def _process(self, topic: str, *args, **kwargs) -> None:
        """
        distribute data to registered event hook in the order of registration
        """
        for event_topic, event_hook in self._event_hooks.items():
            if matched_topic := event_topic.match(topic=topic):
                event_hook.trigger(topic=matched_topic, args=args, kwargs=kwargs)

    def start(self) -> None:
        """
        Start event engine to process events and generate timer events.
        """
        if self._active:
            self.logger.warning(f'{self} already started!')
            return

        self._active = True
        self._engine = Thread(target=self._run, name='EventEngine')
        self._engine.start()

    def stop(self) -> None:
        """
        Stop event engine.
        """
        if not self._active:
            self.logger.warning('EventEngine already stopped!')
            return

        self._active = False
        self._get_lock.release()
        self._engine.join()

    def clear(self) -> None:
        if self._active:
            self.logger.error('EventEngine must be stopped before cleared!')
            return

        self._event_hooks.clear()
        self._deque.clear()

        if self._buffer_size:
            self._put_lock._value = self._buffer_size
            self._get_lock._value = 0

    def put(self, topic: str | Topic, block: bool = True, timeout: float = None, *args, **kwargs):
        """
        fast way to put an event, kwargs MUST NOT contain "topic", "block" and "timeout" keywords
        :param topic: the topic to put into engine
        :param block: block if necessary until a free slot is available
        :param timeout: If 'timeout' is a non-negative number, it blocks at most 'timeout' seconds and raises the Full exception
        :param args: args for handlers
        :param kwargs: kwargs for handlers
        :return: nothing
        """
        self.publish(topic=topic, block=block, timeout=timeout, args=args, kwargs=kwargs)

    def publish(self, topic: str | Topic, block: bool = True, timeout: float = None, args=None, kwargs=None):
        """
        safe way to publish an event
        :param topic: the topic to put into engine
        :param block: block if necessary until a free slot is available
        :param timeout: If 'timeout' is a non-negative number, it blocks at most 'timeout' seconds and raises the Full exception
        :param args: a list / tuple, args for handlers
        :param kwargs: a dict, kwargs for handlers
        :return: nothing
        """
        if isinstance(topic, Topic):
            topic = topic.value
        elif not isinstance(topic, str):
            raise ValueError(f'Invalid topic {topic}')

        if self._buffer_size:
            self._put_lock.acquire()

        event_dict = {'topic': topic}

        if args is not None:
            event_dict['args'] = args

        if kwargs is not None:
            event_dict['kwargs'] = kwargs

        self._deque.append(event_dict)

        self._get_lock.release()

    def register_hook(self, hook: EventHook) -> None:
        """
        register a hook event
        """
        if hook.topic in self._event_hooks:
            for handler in hook.handlers:
                self._event_hooks[hook.topic].add_handler(handler)
        else:
            self._event_hooks[hook.topic] = hook

    def unregister_hook(self, topic: Topic) -> None:
        """
        Unregister an existing hook
        """
        if topic in self._event_hooks:
            self._event_hooks.pop(topic)

    def register_handler(self, topic: Topic, handler: Iterable[Callable] | Callable) -> None:
        """
        Register one or more handler for a specific topic
        """

        if not isinstance(topic, Topic):
            raise TypeError(f'Invalid topic {topic}')

        if topic not in self._event_hooks:
            self._event_hooks[topic] = self.EventHook(topic=topic, handler=handler, logger=self.logger.getChild(topic.value))
        else:
            self._event_hooks[topic].add_handler(handler)

    def unregister_handler(self, topic: Topic, handler: Callable) -> None:
        """
        Unregister an existing handler function.
        """
        if topic in self._event_hooks:
            self._event_hooks[topic].remove_handler(handler=handler)

    @property
    def buffer_size(self):
        return self._buffer_size

    @property
    def active(self) -> bool:
        return self._active


class EventEngine(EventEngineBase):
    EventHook = EventHook

    def __init__(self, buffer_size=0):
        super().__init__(buffer_size=buffer_size)
        self.timer: dict[float | str, Thread] = {}

    def register_handler(self, topic: Topic | str | enum.Enum, handler: Callable):
        topic = Topic.cast(topic)
        super().register_handler(topic=topic, handler=handler)

    def publish(self, topic, block: bool = True, timeout: float = None, args=None, kwargs=None):
        topic = Topic.cast(topic)
        super().publish(topic=topic, block=block, timeout=timeout, args=args, kwargs=kwargs)

    def unregister_hook(self, topic) -> None:
        topic = Topic.cast(topic)
        super().unregister_hook(topic=topic)

    def unregister_handler(self, topic, handler) -> None:
        topic = Topic.cast(topic)

        try:
            super().unregister_handler(topic=topic, handler=handler)
        except ValueError as _:
            raise ValueError(f'unregister topic {topic} failed! handler {handler} not found!')

    def get_timer(self, interval: datetime.timedelta | float | int, activate_time: datetime.datetime = None) -> Topic:
        """
        Start a timer, if not exist, and get topic of the timer event
        :param interval: timer event interval in seconds
        :param activate_time: UTC, timer event only start after active_time. This arg has no effect if timer already started.
        :return: the topic of timer event hook
        """
        if isinstance(interval, datetime.timedelta):
            interval = interval.total_seconds()

        if interval == 1:
            topic = Topic('EventEngine.Internal.Timer.Second')
            timer = Thread(target=self._second_timer, kwargs={'topic': topic})
        elif interval == 60:
            topic = Topic('EventEngine.Internal.Timer.Minute')
            timer = Thread(target=self._minute_timer, kwargs={'topic': topic})
        else:
            topic = Topic(f'EventEngine.Internal.Timer.{interval}')
            timer = Thread(target=self._run_timer, kwargs={'interval': interval, 'topic': topic, 'activate_time': activate_time})

        if interval not in self.timer:
            self.timer[interval] = timer
            timer.start()
        else:
            if activate_time is not None:
                self.logger.debug(f'Timer thread with interval [{datetime.timedelta(seconds=interval)}] already initialized! Argument [activate_time] takes no effect!')

        return topic

    def _run_timer(self, interval: datetime.timedelta | float | int, topic: Topic, activate_time: datetime.datetime = None) -> None:
        if isinstance(interval, datetime.timedelta):
            interval = interval.total_seconds()

        if activate_time is None:
            scheduled_time = datetime.datetime.utcnow()
        else:
            scheduled_time = activate_time

        while self._active:
            sleep_time = (scheduled_time - datetime.datetime.utcnow()).total_seconds()

            if sleep_time > 0:
                time.sleep(sleep_time)
            self.put(topic=topic, interval=interval, trigger_time=scheduled_time)

            while scheduled_time < datetime.datetime.utcnow():
                scheduled_time += datetime.timedelta(seconds=interval)

    def _minute_timer(self, topic: Topic):
        while self._active:
            t = time.time()
            scheduled_time = t // 60 * 60
            next_time = scheduled_time + 60
            sleep_time = next_time - t
            time.sleep(sleep_time)
            self.put(topic=topic, interval=60., timestamp=scheduled_time)

    def _second_timer(self, topic: Topic):
        while self._active:
            t = time.time()
            scheduled_time = t // 1
            next_time = scheduled_time + 1
            sleep_time = next_time - t
            time.sleep(sleep_time)
            self.put(topic=topic, interval=1., timestamp=scheduled_time)

    def stop(self) -> None:
        super().stop()

        for timer in self.timer.values():
            timer.join()

    def clear(self) -> None:
        for t in self.timer.values():
            t.join(timeout=0)

        self.timer.clear()
