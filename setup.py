import codecs
import os

import setuptools.extension
from bokeh.embed import standalone


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


long_description = read("README.md")

setuptools.setup(
    name="PyEventEngine",
    version=get_version(os.path.join('event_engine', '__init__.py')),
    author="Bolun.Han",
    author_email="Bolun.Han@outlook.com",
    description="Basic event engine",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/BolunHan/PyEventEngine.git",
    packages=setuptools.find_packages(),
    include_package_data=True,
    package_data={
    },
    classifiers=[
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.8',
    license='MIT',
    install_requires=[],
    ext_modules=[
        setuptools.extension.Extension(r'event_engine.topic_api', sources=[r'event_engine/cpp/topic_api.cpp'], include_dirs=[], language='c++', optional=True),
        setuptools.extension.Extension(r'event_engine.event_api', sources=[r'event_engine/cpp/event_api.cpp'], include_dirs=[], language='c++', optional=True)
    ],
    command_options={
        'nuitka': {
            # boolean option, e.g. if you cared for C compilation commands
            '--show-scons': ("setup.py", True),
            # options without value, e.g. enforce using Clang
            '--clang': ("setup.py", None),
            # options with single values, e.g. enable a plugin of Nuitka
            # '--enable-plugin': ("setup.py", "pyside2"),
            # options with several values, e.g. avoiding including modules
            # '--nofollow-import-to': ("setup.py", ["*.tests", "*.distutils"]),
        }
    }
)
