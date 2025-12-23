import codecs
import os

import setuptools
from Cython.Build import cythonize
from setuptools.command.build_ext import build_ext
from setuptools.extension import Extension


def read(rel_path):
    here = os.path.abspath(os.path.dirname(__file__))
    # intentionally *not* adding an encoding option to open, See:
    #   https://github.com/pypa/virtualenv/issues/201#issuecomment-3145690
    with codecs.open(os.path.join(here, rel_path), 'r') as fp:
        return fp.read()


def get_version(rel_path):
    for line in read(rel_path).splitlines():
        if line.startswith('__version__'):
            # __version__ = "0.9"
            delim = '"' if '"' in line else "'"
            return line.split(delim)[1]
    raise RuntimeError("Unable to find version string.")


cython_extension = []
ext_modules = []
opt_flags = []
with_annotation = False

match os.environ.get("PYEE_OPT", "").lower():
    case "debug":
        with_annotation = True
        opt_flags = ["-g", "-O0"]
    case "size":
        opt_flags = ["-Os"]
    case "fast":
        opt_flags = ["-O3", "-ffast-math"]
    case "none":
        opt_flags = []
    case _:  # default to -O3
        opt_flags = ["-O3"]

if os.name == 'posix':
    cython_extension.extend([
        Extension(
            name="event_engine.base.c_strmap",
            sources=["event_engine/base/c_strmap.pyx"],
            extra_compile_args=opt_flags,
        ),
        Extension(
            name="event_engine.capi.c_topic",
            sources=["event_engine/capi/c_topic.pyx"],
            extra_compile_args=opt_flags,
            include_dirs=["event_engine/base"]
        ),
        Extension(
            name="event_engine.capi.c_event",
            sources=["event_engine/capi/c_event.pyx"],
            extra_compile_args=opt_flags,
            include_dirs=["event_engine/base"]
        ),
        Extension(
            name="event_engine.capi.c_engine",
            sources=["event_engine/capi/c_engine.pyx"],
            extra_compile_args=opt_flags,
            include_dirs=["event_engine/base"]
        ),
    ])


class BuildExtWithConfig(build_ext):
    def build_extensions(self):
        macros = []
        for macro in ["DEBUG"]:
            val = os.environ.get(macro)
            if val:
                print(f'Compile-time variable {macro} overridden with value {val}')
                macros.append((macro, val))
        for ext in self.extensions:
            ext.define_macros = macros
        build_ext.build_extensions(self)


ext_modules.extend(cythonize(cython_extension, annotate=with_annotation, compiler_directives={"language_level": "3"}))

setuptools.setup(
    name="PyEventEngine",
    ext_modules=ext_modules,
    cmdclass={"build_ext": BuildExtWithConfig},
)
