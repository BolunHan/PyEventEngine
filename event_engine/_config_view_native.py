"""Pure-Python fallback for the compiled ``event_engine.config_view``.

``config_view`` is a Cython extension whose module init imports the capi
extensions, so on a source checkout without a Cython build (or when capi is
blocked/unavailable) it cannot load.  The top-level package then uses this
module's view instead, keeping ``import event_engine`` working so the
capi -> native fallback can engage.

The structure mirrors the compiled view, and the values are the native
layer's public defaults, which pin the same documented values as the default
C build (cross-checked by tests/windows/test_03_package.py).  The compiled
extension remains the source of truth whenever it is available.
"""

from types import MappingProxyType

from .native.engine import (
    DEFAULT_MQ_CAPACITY,
    DEFAULT_MQ_SPIN_LIMIT,
    DEFAULT_MQ_TIMEOUT_SECONDS,
)
from .native.topic import (
    DEFAULT_OPTION_SEP,
    DEFAULT_PATTERN_DELIM,
    DEFAULT_RANGE_BRACKETS,
    DEFAULT_TOPIC_SEP,
    DEFAULT_WILDCARD_BRACKETS,
    DEFAULT_WILDCARD_MARKER,
)

_config_view = {
    "engine": {
        "DEFAULT_MQ_CAPACITY": DEFAULT_MQ_CAPACITY,
        "DEFAULT_MQ_SPIN_LIMIT": DEFAULT_MQ_SPIN_LIMIT,
        "DEFAULT_MQ_TIMEOUT_SECONDS": DEFAULT_MQ_TIMEOUT_SECONDS,
    },
    "topic": {
        "DEFAULT_TOPIC_SEP": DEFAULT_TOPIC_SEP,
        "DEFAULT_OPTION_SEP": DEFAULT_OPTION_SEP,
        "DEFAULT_RANGE_BRACKETS": DEFAULT_RANGE_BRACKETS,
        "DEFAULT_WILDCARD_BRACKETS": DEFAULT_WILDCARD_BRACKETS,
        "DEFAULT_WILDCARD_MARKER": DEFAULT_WILDCARD_MARKER,
        "DEFAULT_PATTERN_DELIM": DEFAULT_PATTERN_DELIM,
    },
    # The default C build ships heap-only (no SHM); overridable at compile
    # time via the EE_LOCAL_ONLY macro.
    "allocator": {"EE_LOCAL_ONLY": True},
}

CONFIG_VIEW = MappingProxyType({
    name: MappingProxyType(section) for name, section in _config_view.items()
})
