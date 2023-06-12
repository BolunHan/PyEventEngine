from __future__ import annotations

import re
from enum import Enum
from string import Formatter


class Topic(dict):
    """
    topic for event hook. e.g. "TickData.002410.SZ.Realtime"
    """

    class Error(Exception):
        def __init__(self, msg):
            super().__init__(msg)

    def __init__(self, topic: str, *args, **kwargs):
        self._value = topic
        super().__init__(*args, **kwargs)

    def __repr__(self):
        return f'<{self.__class__.__name__}>({self._value}){super().__repr__()}'

    def __str__(self):
        return self.value

    def __bool__(self):
        return True

    def __hash__(self):
        return self.value.__hash__()

    def match(self, topic: str) -> Topic | None:
        if self._value == topic:
            return self.__class__(topic=topic)
        else:
            return None

    @classmethod
    def cast(cls, topic: Topic | str | Enum, dtype=None) -> Topic:
        if isinstance(topic, Enum):
            topic = topic.value
        elif isinstance(topic, Topic):
            return topic

        if dtype is None:
            if re.search(r'{(.+?)}', topic):
                t = PatternTopic(pattern=topic)
            elif '*' in topic or '+' in topic or '|' in topic:
                re.compile(pattern=topic)
                t = RegularTopic(pattern=topic)
            else:
                t = Topic(topic=topic)
        else:
            t = dtype(topic)

        return t

    @property
    def value(self) -> str:
        return self._value


class RegularTopic(Topic):
    """
    topic in regular expression. e.g. "TickData.(.+).((SZ)|(SH)).((Realtime)|(History))"
    """

    def __init__(self, pattern: str):
        super().__init__(topic=pattern)

    def match(self, topic: str) -> Topic | None:
        if re.match(self._value, topic):
            match = Topic(topic=topic)
            match['pattern'] = self._value
            return match
        else:
            return None


class PatternTopic(Topic):
    """
    topic for event hook. e.g. "TickData.{symbol}.{market}.{flag}"
    """

    def __init__(self, pattern: str):
        super().__init__(topic=pattern)

    def __call__(self, **kwargs):
        return self.format_map(kwargs)

    # @classmethod
    # def extract_mapping(cls, target: str, pattern: str):
    #     pattern = re.escape(pattern)
    #     regex = re.sub(r'\\{(.+?)\\}', r'(?P<_\1>.+)', pattern)
    #     match = re.match(regex, target)
    #     if match:
    #         values = list(match.groups())
    #         keys = re.findall(r'\\{(.+?)\\}', pattern)
    #         m = dict(zip(keys, values))
    #         return m
    #     else:
    #         raise Topic.Error(f'pattern {pattern} not in string {target} found!')

    @classmethod
    def extract_mapping(cls, target, pattern):
        dictionary = {}

        result_parts = target.split('.')
        pattern_parts = pattern.split('.')

        # Check if the number of parts in result and pattern are the same
        if len(result_parts) != len(pattern_parts):
            return dictionary

        # Generate the mapping dictionary
        num_parts = len(result_parts)
        for i in range(num_parts):
            result_part = result_parts[i]
            pattern_part = pattern_parts[i]

            if pattern_part[0] == '{' and pattern_part[-1] == '}':
                content = pattern_part[1:-1]
                dictionary[content] = result_part
            else:
                if result_part != pattern_part:
                    dictionary.clear()
                    return dictionary

        return dictionary

    def format_map(self, mapping: dict) -> Topic:
        for key in self.keys():
            if key not in mapping:
                mapping[key] = f'{{{key}}}'

        return Topic.cast(self._value.format_map(mapping))

    def keys(self):
        keys = [i[1] for i in Formatter().parse(self._value) if i[1] is not None]
        return keys

    def match(self, topic: str) -> Topic | None:
        try:
            keyword_dict = self.extract_mapping(target=topic, pattern=self._value)
            match = Topic(topic=topic)
            match.update(keyword_dict)
            return match
        except self.Error as _:
            return None

    @property
    def value(self) -> str:
        return self._value.format_map({_: '*' for _ in self.keys()})
