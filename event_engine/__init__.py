__version__ = '0.5.2.post1'

import functools
import pathlib

try:
    from .capi import *  # noqa: F401,F403
except Exception as e:
    import warnings

    warnings.warn(
        f"Failed to import event_engine.capi ({e!r}); falling back to event_engine.native.",
        ImportWarning,
        stacklevel=2,
    )
    from .native import *  # noqa: F401,F403


@functools.cache
def get_include() -> list[str]:
    import os
    from .base import LOGGER

    res_dir = pathlib.Path(__file__).parent
    LOGGER.info(f'Building with <PyEventEngine> version: "{__version__}", resource directory: "{res_dir}".')

    scr_dir = [
        os.path.realpath(res_dir),
        os.path.realpath(res_dir / 'base'),
        os.path.realpath(res_dir / 'capi'),
    ]

    include_root = os.path.realpath(res_dir / 'include')
    if os.path.isdir(include_root):
        scr_dir.append(include_root)

    return scr_dir
