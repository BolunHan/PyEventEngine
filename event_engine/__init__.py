__version__ = '0.4.3'

import functools
import os

if os.name == 'posix':
    from .capi import *
else:
    from .native import *


@functools.cache
def get_include():
    import os
    from .base import LOGGER

    res_dir = os.path.dirname(__file__)
    LOGGER.info(f'Building with <PyEventEngine> version: "{__version__}", resource directory: "{res_dir}".')
    return res_dir
