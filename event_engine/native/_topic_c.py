from __future__ import annotations

import ctypes
import pathlib
import platform
import re

from ._topic import Topic, RegularTopic as RegularTopicBase, PatternTopic as PatternTopicBase

__all__ = ['Topic', 'RegularTopic', 'PatternTopic']

topic_lib = None

if platform.system() == 'Windows':
    package_name = 'topic_api.(.*).pyd'
elif platform.system() == 'Darwin':
    package_name = '^topic_api(.*).so$'
else:
    package_name = '^topic_api(.*).so$'

ROOT_DIR = pathlib.Path(__file__).parent.parent
ENCODING = 'utf-8'

for _ in ROOT_DIR.iterdir():
    if lib_path := re.search(package_name, _.name):
        topic_lib = ctypes.CDLL(str(_))
        break

# Load the shared library
if topic_lib is None:
    raise ImportError(f'EventEngine.Topic c extension {package_name} not found in {ROOT_DIR}! Fallback to native lib!')

# Function prototypes
# topic_lib.delete_vector.restype = [ctypes.POINTER]
topic_lib.get_vector_value.restype = ctypes.c_char_p
topic_lib.is_regular_match.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
topic_lib.is_regular_match.restype = ctypes.c_int


# Define the RegularTopic class in Python
class RegularTopic(RegularTopicBase):
    """
    topic in regular expression. e.g. "TickData.(.+).((SZ)|(SH)).((Realtime)|(History))"
    """

    def match(self, topic: str):
        match = topic_lib.is_regular_match(topic.encode(ENCODING), self._value.encode(ENCODING))

        if match:
            return Topic(topic=topic, pattern=self.value)
        else:
            return None


# Define the PatternTopic class in Python
class PatternTopic(PatternTopicBase):
    """
    topic for event hook. e.g. "TickData.{symbol}.{market}.{flag}"
    """

    def match(self, topic: str):
        mapping = self.extract_mapping(target=topic, pattern=self._value, encoding=ENCODING)

        if mapping:
            return Topic(topic, pattern=self._value, **mapping)
        else:
            return None

    @classmethod
    def extract_mapping(cls, target: str, pattern: str, encoding: str = ENCODING) -> dict[str, str]:
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
            key = topic_lib.get_vector_value(ctypes.byref(keys_ptr), i)
            value = topic_lib.get_vector_value(ctypes.byref(values_ptr), i)
            # print(key, value)
            mapping[key.decode(encoding)] = value.decode(encoding)

        # topic_lib.delete_vector(ctypes.byref(keys_ptr))
        # topic_lib.delete_vector(ctypes.byref(values_ptr))

        del keys_ptr
        del values_ptr

        return mapping
