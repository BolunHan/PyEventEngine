__version__ = '0.4.6'

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

    res_dir = os.path.dirname(__file__)
    LOGGER.info(f'Building with <PyEventEngine> version: "{__version__}", resource directory: "{res_dir}".')
    return [res_dir, pathlib.Path(res_dir).joinpath('base').__str__(), pathlib.Path(res_dir).joinpath('capi').__str__()]
