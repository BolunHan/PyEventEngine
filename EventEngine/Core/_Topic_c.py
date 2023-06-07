from __future__ import annotations

import ctypes
import pathlib
import re

__all__ = ['Topic', 'RegularTopic', 'PatternTopic']

topic_lib = None
package_name = '^topic_api(.*).so$'
root_dir = pathlib.Path(__file__).parent.parent

for _ in root_dir.iterdir():
    if lib_path := re.search(package_name, _.name):
        topic_lib = ctypes.CDLL(str(_))
        break

# Load the shared library
if topic_lib is None:
    raise ImportError(f'EventEngine.Topic c extension {package_name} not found in {root_dir}! Fallback to native lib!')

# Function prototypes
handler = ctypes.POINTER(ctypes.c_void_p)

topic_lib.create_topic.restype = handler
topic_lib.create_regular_topic.restype = handler
topic_lib.create_pattern_topic.restype = handler

topic_lib.get_topic_value.restype = ctypes.c_void_p
topic_lib.get_topic_value_no_buffer.restype = ctypes.POINTER(ctypes.c_char_p)
topic_lib.get_vector_value.restype = ctypes.c_char_p

topic_lib.match_topic.restype = handler
topic_lib.match_regular_topic.restype = handler
topic_lib.match_pattern_topic.restype = handler

topic_lib.get_pattern_topic_keys.restype = handler


class Topic(dict):
    """
    topic for event hook. e.g. "TickData.002410.SZ.Realtime"
    """

    def __init__(self, topic: str, encoding: str = 'utf-8', buffer_size: int = 0, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.encoding = encoding
        self.buffer_size = buffer_size
        self.topic = topic_lib.create_topic(topic.encode(self.encoding))

    def __repr__(self):
        return f'<{self.__class__.__name__}>({self.value}){super().__repr__()}'

    def __str__(self):
        return self.value

    def __bool__(self):
        if self.value:
            return True
        else:
            return False

    def __hash__(self):
        return self.value.__hash__()

    @staticmethod
    def _get_topic_value(topic: handler | int, buffer_size: int = 1024, encoding: str = 'utf-8'):
        if buffer_size:
            buffer = ctypes.create_string_buffer(buffer_size)
            topic_lib.get_topic_value(topic, buffer, buffer_size)
            topic_value = buffer.value.decode(encoding)
        else:
            topic_ptr = topic_lib.get_topic_value_no_buffer(topic)
            topic_value = ctypes.string_at(topic_ptr).decode(encoding)

        return topic_value

    @property
    def value(self) -> str:
        return self._get_topic_value(topic=self.topic, buffer_size=self.buffer_size, encoding=self.encoding)

    def match(self, topic: str):
        match = topic_lib.match_topic(self.topic, topic.encode(self.encoding))

        if self._get_topic_value(match):
            return Topic(topic)
        else:
            return None

    def __del__(self):
        topic_lib.delete_topic(self.topic)


# Define the RegularTopic class in Python
class RegularTopic(Topic):
    """
    topic in regular expression. e.g. "TickData.(.+).((SZ)|(SH)).((Realtime)|(History))"
    """

    def __init__(self, pattern: str, encoding: str = 'utf-8', buffer_size: int = 0, *args, **kwargs):
        dict.__init__(self, *args, **kwargs)
        self.encoding = encoding
        self.buffer_size = buffer_size
        self.topic = topic_lib.create_pattern_topic(pattern.encode(self.encoding))

    def match(self, topic: str):
        match = topic_lib.match_regular_topic(self.topic, topic.encode(self.encoding))

        if _ := self._get_topic_value(match):
            return Topic(_, pattern=self.value)
        else:
            return None


# Define the PatternTopic class in Python
class PatternTopic(Topic):
    """
    topic for event hook. e.g. "TickData.{symbol}.{market}.{flag}"
    """

    def __init__(self, pattern: str, encoding: str = 'utf-8', buffer_size: int = 0, *args, **kwargs):
        dict.__init__(self, *args, **kwargs)
        self.encoding = encoding
        self.buffer_size = buffer_size
        self.topic = topic_lib.create_regular_topic(pattern.encode(self.encoding))

    def __call__(self, **kwargs):
        return self.format_map(kwargs)

    def match(self, topic: str):
        match = topic_lib.match_pattern_topic(self.topic, topic.encode(self.encoding))

        if _ := self._get_topic_value(match):
            return Topic(_, pattern=self.value, **self.extract_mapping(target=topic, pattern=self.value, encoding=self.encoding))
        else:
            return None

    @classmethod
    def extract_mapping(cls, target: str, pattern: str, encoding: str = 'utf-8') -> dict[str, str]:
        # noinspection PyArgumentList
        keys_ptr, values_ptr = ctypes.POINTER(ctypes.c_void_p)(), ctypes.POINTER(ctypes.c_void_p)()
        mapping = {}

        topic_lib.extract_mapping(
            target.encode(encoding),
            pattern.encode(encoding),
            ctypes.byref(keys_ptr),
            ctypes.byref(values_ptr)
        )

        for i in range(topic_lib.vector_size(ctypes.byref(keys_ptr))):
            mapping[topic_lib.get_vector_value(ctypes.byref(keys_ptr), i).decode(encoding)] = topic_lib.get_vector_value(ctypes.byref(values_ptr), i).decode(encoding)

        return mapping

    def keys(self) -> list[str]:
        keys = []
        keys_ptr = topic_lib.get_pattern_topic_keys(self.topic)

        for i in range(topic_lib.vector_size(keys_ptr)):
            keys.append(topic_lib.get_vector_value(keys_ptr, i).decode(self.encoding))

        topic_lib.delete_vector(keys_ptr)
        return keys

    def format_map(self, mapping: dict) -> Topic:
        for key in self.keys():
            if key not in mapping:
                mapping[key] = f'{{{key}}}'

        return Topic(self.value.format_map(mapping))
