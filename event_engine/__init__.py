__version__ = '0.4.1'

import os

if os.name == 'posix':
    from .capi import *
else:
    from .native import *
