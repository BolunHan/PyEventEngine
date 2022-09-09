from __future__ import annotations

import datetime
import queue
import threading
import time
import traceback
from typing import Iterable

from . import LOGGER, LOG_LEVEL_EVENT
from ._Topic import Topic


class EventHookBase(object):
    """
    Event object with
    a string topic for event engine to distribute event,
    and a list of handler to process data
    """

    def __init__(self, topic: Topic, handler: list[callable] | callable | None = None):
        self.topic = topic

        if callable(handler):
            self.handlers = [handler]
        elif isinstance(handler, Iterable):
            self.handlers = []
            for hdl in handler:
                if callable(hdl):
                    self.handlers.append(hdl)
                else:
                    raise ValueError(f'invalid handler {hdl}')
        elif handler is None:
            self.handlers = []
        else:
            raise ValueError(f'Invalid handler {handler}')

    def __call__(self, *args, **kwargs):
        self.trigger(topic=self.topic, args=args, kwargs=kwargs)

    def __iadd__(self, handler):
        self.add_handler(handler)
        return self

    def __isub__(self, handler):
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
                except TypeError:
                    handler(*args, **kwargs)
            except Exception as _:
                LOGGER.error(traceback.format_exc())

    def add_handler(self, handler: callable):
        self.handlers.append(handler)

    def remove_handler(self, handler: callable):
        self.handlers.remove(handler)


class EventHook(EventHookBase):
    def __init__(self, topic, handler):
        self.logger = LOGGER.getChild(f'EventHook.{topic}')
        super().__init__(topic=topic, handler=handler)

    def trigger(self, topic: Topic, args: tuple = None, kwargs: dict = None):
        ts = time.time()

        if args is None:
            args = ()

        if kwargs is None:
            kwargs = {}

        for handler in self.handlers:
            try:
                try:
                    handler(topic=topic, *args, **kwargs)
                except TypeError:
                    handler(*args, **kwargs)
            except Exception as _:
                self.logger.error(traceback.format_exc())

        self.logger.log(LOG_LEVEL_EVENT, f'EventHook {self.topic} tasks triggered {len(self.handlers):,} handlers, complete in {(time.time() - ts) * 1000:.3f}ms')


class EventEngineBase(object):
    EventHook = EventHook

    def __init__(self, max_size=0):
        self.lock = threading.Lock()

        self._max_size = max_size
        self._queue: queue.Queue = queue.Queue(maxsize=self._max_size)
        self._active: bool = False
        self._engine: threading.Thread = threading.Thread(target=self._run, name='EventEngine')
        self._event_hooks: dict[Topic, EventHook] = {}

    def _run(self) -> None:
        """
        Get event from queue and then process it.
        """
        while self._active:
            try:
                event_dict = self._queue.get(block=True, timeout=1)
                topic = event_dict['topic']
                args = event_dict.get('args', ())
                kwargs = event_dict.get('kwargs', {})
                self._process(topic, *args, **kwargs)
            except queue.Empty:
                pass

    def _process(self, topic: str, *args, **kwargs) -> None:
        """
        distribute data to registered event hook in the order of registration
        """
        for _ in list(self._event_hooks):
            m = _.match(topic=topic)
            if m:
                event_hook = self._event_hooks.get(_)

                if event_hook is not None:
                    event_hook.trigger(topic=m, args=args, kwargs=kwargs)

    def start(self) -> None:
        """
        Start event engine to process events and generate timer events.
        """
        self._active = True
        self._engine.start()

    def stop(self) -> None:
        """
        Stop event engine.
        """
        self._active = False
        self._engine.join()

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

        event_dict = {'topic': topic}

        if args is not None:
            event_dict['args'] = args

        if kwargs is not None:
            event_dict['kwargs'] = kwargs

        self._queue.put(event_dict, block=block, timeout=timeout)

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

    def register_handler(self, topic: Topic, handler: Iterable[callable] | callable) -> None:
        """
        Register one or more handler for a specific topic
        """

        if not isinstance(topic, Topic):
            raise TypeError(f'Invalid topic {topic}')

        if topic not in self._event_hooks:
            self._event_hooks[topic] = self.EventHook(topic=topic, handler=handler)
        else:
            self._event_hooks[topic].add_handler(handler)

    def unregister_handler(self, topic: Topic, handler: callable) -> None:
        """
        Unregister an existing handler function.
        """
        if topic in self._event_hooks:
            self._event_hooks[topic].remove_handler(handler=handler)

    @property
    def max_size(self):
        return self._max_size

    @max_size.setter
    def max_size(self, size: int):
        self._max_size = size
        self._queue.maxsize = size


class EventEngine(EventEngineBase):
    EventHook = EventHook

    def __init__(self, max_size=0):
        super().__init__(max_size=max_size)
        self.timer: dict[float | str, threading.Thread] = {}

    def register_handler(self, topic, handler):
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
            timer = threading.Thread(target=self._second_timer, kwargs={'topic': topic})
        elif interval == 60:
            topic = Topic('EventEngine.Internal.Timer.Minute')
            timer = threading.Thread(target=self._minute_timer, kwargs={'topic': topic})
        else:
            topic = Topic(f'EventEngine.Internal.Timer.{interval}')
            timer = threading.Thread(target=self._run_timer, kwargs={'interval': interval, 'topic': topic, 'activate_time': activate_time})

        if interval not in self.timer:
            self.timer[interval] = timer
            timer.start()
        else:
            if activate_time is not None:
                LOGGER.debug(f'Timer thread with interval [{datetime.timedelta(seconds=interval)}] already initialized! Argument [activate_time] takes no effect!')

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
            self.put(topic=topic)

            while scheduled_time < datetime.datetime.utcnow():
                scheduled_time += datetime.timedelta(seconds=interval)

    def _minute_timer(self, topic: Topic):
        while self._active:
            t = datetime.datetime.utcnow()
            sleep_time = 60 - (t.second + t.microsecond / 1000000.0)
            time.sleep(sleep_time)
            self.put(topic=topic)

    def _second_timer(self, topic: Topic):
        while self._active:
            t = datetime.datetime.utcnow()
            sleep_time = 1 - t.microsecond / 1000000.0
            time.sleep(sleep_time)
            self.put(topic=topic)

    def stop(self) -> None:
        super().stop()

        for timer in self.timer.values():
            timer.join()
