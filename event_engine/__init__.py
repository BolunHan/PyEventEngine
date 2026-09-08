__version__ = '1.0.2'

import functools
import pathlib
import warnings
from collections.abc import Mapping

from .base import LOGGER

try:
    # Compiled registry - source of truth for the C build configuration.
    from .config_view import CONFIG_VIEW
except Exception as e:
    # config_view is a Cython extension whose module init imports the capi
    # extensions; on source checkouts without a Cython build (or when capi
    # is blocked/unavailable) it cannot load. Keep `import event_engine`
    # working so the capi -> native fallback below can engage - the native
    # defaults mirror the documented compile-time values.
    warnings.warn(
        f"Compiled config_view unavailable ({e!r}); using native config defaults.",
        ImportWarning,
        stacklevel=2,
    )
    from ._config_view_native import CONFIG_VIEW

try:
    from .capi import *  # noqa: F401,F403
except Exception as e:
    warnings.warn(
        f"Failed to import event_engine.capi ({e!r}); falling back to event_engine.native.",
        ImportWarning,
        stacklevel=2,
    )
    from .native import *  # noqa: F401,F403


def _format_config_view(config: Mapping, indent: int = 0) -> str:
    """Render a (possibly nested) config view as indented bullet lines."""
    lines = []
    for key, value in config.items():
        if isinstance(value, Mapping):
            lines.append(f"{'  ' * indent}- {key}:")
            lines.append(_format_config_view(value, indent + 1))
        else:
            lines.append(f"{'  ' * indent}- {key}: {value}")
    return "\n".join(lines)


@functools.cache
def get_include() -> list[str]:
    import os

    res_dir = pathlib.Path(__file__).parent
    LOGGER.info(
        f'Building with <PyEventEngine> version: "{__version__}", resource directory: "{res_dir}", '
        f"config:\n{_format_config_view(CONFIG_VIEW)}"
    )

    scr_dir = [
        os.path.realpath(res_dir),
        os.path.realpath(res_dir / 'base'),
        os.path.realpath(res_dir / 'capi'),
    ]

    include_root = os.path.realpath(res_dir / 'includes')
    if os.path.isdir(include_root):
        scr_dir.append(include_root)

    return scr_dir


__all__ = [
    'CONFIG_VIEW',
    'get_include',
    'LOGGER',
]
