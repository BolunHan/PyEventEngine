# config_view.pyx — compile-time macro registry for PyEventEngine
#
# Exposes every overridable compile-time constant as a read-only,
# per-submodule nested mappingproxy (CONFIG_VIEW) so that downstream code
# and diagnostics can inspect the build configuration at runtime.

from event_engine.base.c_allocator_protocol cimport EE_LOCAL_ONLY
from event_engine.capi.c_engine cimport (
    DEFAULT_MQ_CAPACITY, DEFAULT_MQ_SPIN_LIMIT, DEFAULT_MQ_TIMEOUT_SECONDS,
)
from event_engine.capi.c_topic cimport (
    DEFAULT_TOPIC_SEP, DEFAULT_OPTION_SEP,
    DEFAULT_RANGE_BRACKETS, DEFAULT_WILDCARD_BRACKETS,
    DEFAULT_WILDCARD_MARKER, DEFAULT_PATTERN_DELIM,
)


cdef inline str _cchar(const char c):
    """Decode a single C char to a Python str."""
    return chr(c)


cdef inline str _cstr(const char* s):
    """Decode a C string (bytes) to a Python str."""
    return s.decode()


# -- Internal (mutable) dict, nested per submodule -------------------------
cdef dict _config_view = {
    'engine': {
        'DEFAULT_MQ_CAPACITY':         DEFAULT_MQ_CAPACITY,
        'DEFAULT_MQ_SPIN_LIMIT':       DEFAULT_MQ_SPIN_LIMIT,
        'DEFAULT_MQ_TIMEOUT_SECONDS':  DEFAULT_MQ_TIMEOUT_SECONDS,
    },

    'topic': {
        'DEFAULT_TOPIC_SEP':           _cchar(DEFAULT_TOPIC_SEP),
        'DEFAULT_OPTION_SEP':          _cchar(DEFAULT_OPTION_SEP),
        'DEFAULT_RANGE_BRACKETS':      _cstr(DEFAULT_RANGE_BRACKETS),
        'DEFAULT_WILDCARD_BRACKETS':   _cstr(DEFAULT_WILDCARD_BRACKETS),
        'DEFAULT_WILDCARD_MARKER':     _cchar(DEFAULT_WILDCARD_MARKER),
        'DEFAULT_PATTERN_DELIM':       _cchar(DEFAULT_PATTERN_DELIM),
    },

    'allocator': {
        'EE_LOCAL_ONLY':               EE_LOCAL_ONLY,
    },
}


# -- Public read-only view (nested proxies, immutable at every level) -----
from types import MappingProxyType
CONFIG_VIEW = MappingProxyType({
    name: MappingProxyType(section) for name, section in _config_view.items()
})
