import codecs
import os
import shutil
import sys
from contextlib import suppress
from pathlib import Path

import setuptools
from Cython.Build import cythonize
from setuptools.command.build_ext import build_ext
from setuptools.extension import Extension


class BuildExtWithConfig(build_ext):
    def run(self):
        self.pre_compile()

        super().run()

        self.post_compile()

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

    def pre_compile(self):
        self.remove_pxd(
            [
                "event_engine.capi",
            ]
        )

    def post_compile(self):
        # Monkey hack the "__init__.pxd" issue:
        self.inject_pxd(
            [
                "event_engine.capi",
            ]
        )

    def remove_pxd(self, modules: list[str]) -> None:
        project_root = Path(__file__).resolve().parent

        for module in modules:
            src_dir = project_root.joinpath(*module.split("."))
            init_pxd = src_dir / "__init__.pxd"

            if init_pxd.exists():
                print(f"[pre_compile] Removing {init_pxd}")
                with suppress(FileNotFoundError):
                    init_pxd.unlink()

    def inject_pxd(self, modules: list[str]) -> None:
        for module in modules:
            project_root = Path(__file__).resolve().parent
            src_dir = project_root.joinpath(*module.split("."))
            pkg_dir = Path(self.build_lib, *module.split("."))

            infra_pxd = src_dir / "__infra__.pxd"
            if not infra_pxd.exists():
                continue

            pkg_dir.mkdir(parents=True, exist_ok=True)
            init_pxd = pkg_dir / "__init__.pxd"

            print(f"[build_py] Injecting {infra_pxd} -> {init_pxd}")
            shutil.copyfile(infra_pxd, init_pxd)


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
with_annotation = False
mode = os.environ.get("PYEE_OPT", "").lower()

if os.name == "nt":
    match mode:
        case "debug":
            with_annotation = True
            flags = ["/Od", "/Zi"]
        case "size":
            flags = ["/O1"]
        case "fast":
            flags = ["/O2", "/fp:fast"]
        case "none":
            flags = ["/Od"]
        case _:
            flags = ["/O2"]
    flags.append("/std:clatest")
    flags.append("/experimental:c11atomics")
else:  # gcc / clang / apple clang
    match mode:
        case "debug":
            with_annotation = True
            flags = ["-g", "-O0"]
        case "size":
            flags = ["-Os"]
        case "fast":
            flags = ["-O3", "-ffast-math"]
        case "none":
            flags = []
        case _:
            flags = ["-O3"]
    flags.append("-std=c23")

cython_extension.extend([
    Extension(
        name="event_engine.base.c_strmap",
        sources=["event_engine/base/c_strmap.pyx"],
        extra_compile_args=list(flags),
    ),
    Extension(
        name="event_engine.capi.c_topic",
        sources=["event_engine/capi/c_topic.pyx"],
        extra_compile_args=list(flags),
        include_dirs=["event_engine/base"]
    ),
    Extension(
        name="event_engine.capi.c_event",
        sources=["event_engine/capi/c_event.pyx"],
        extra_compile_args=list(flags),
        include_dirs=["event_engine/base"]
    ),
    Extension(
        name="event_engine.capi.c_engine",
        sources=["event_engine/capi/c_engine.pyx"],
        extra_compile_args=list(flags),
        include_dirs=["event_engine/base"]
    ),
])

ext_modules.extend(cythonize(cython_extension, annotate=with_annotation, compiler_directives={"language_level": "3"}, force="--force" in sys.argv))

setuptools.setup(
    name="PyEventEngine",
    ext_modules=ext_modules,
    cmdclass={"build_ext": BuildExtWithConfig},
)
