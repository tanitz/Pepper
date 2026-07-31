# -*- coding: utf-8 -*-
# naoqi_path.py  –  locate the pynaoqi SDK directory that holds the `qi` package.
#
# The Windows and Linux builds of pynaoqi 2.8.7 use different layouts:
#   Windows:  SDK_pynaoqi/pynaoqi/lib/                              (_qi.pyd + *.dll)
#   Linux:    SDK_pynaoqi/linux64/lib/python2.7/site-packages/      (_qi.so)
# so the right one has to be chosen at runtime rather than hard-coded.

import glob
import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
_SDK = os.path.join(_ROOT, "SDK_pynaoqi")

_DOWNLOAD_HINT = (
    "Windows: extract pynaoqi so this path exists:\n"
    "    SDK_pynaoqi/pynaoqi/lib/_qi.pyd\n"
    "Linux:   bash scripts/download_pynaoqi_linux.sh\n"
    "    (expects SDK_pynaoqi/linux64/lib/python2.7/site-packages/_qi.so)\n"
    "Or set PYNAOQI_LIB to the folder that contains the native _qi module."
)


def _patterns():
    """Glob patterns for the SDK lib dir, most specific first."""
    if sys.platform.startswith("win"):
        return [os.path.join(_SDK, "pynaoqi", "lib")]
    return [
        os.path.join(_SDK, "linux64", "lib", "python*", "site-packages"),
        # tarball extracted without renaming the versioned top-level directory
        os.path.join(_SDK, "pynaoqi-python2.7-*-linux64*", "lib", "python*", "site-packages"),
        # Linux tree dropped into the directory the Windows build used
        os.path.join(_SDK, "pynaoqi", "lib", "python*", "site-packages"),
    ]


def _native_module_glob():
    return "_qi*.pyd" if sys.platform.startswith("win") else "_qi*.so"


def _has_native_module(path):
    return bool(glob.glob(os.path.join(path, _native_module_glob())))


def find_sdk_lib():
    """Return the SDK directory containing the native _qi module.

    Set PYNAOQI_LIB to override the search entirely.
    """
    override = os.environ.get("PYNAOQI_LIB")
    if override:
        if not _has_native_module(override):
            raise ImportError(
                "PYNAOQI_LIB is set to '%s' but no %s was found there.\n%s"
                % (override, _native_module_glob(), _DOWNLOAD_HINT)
            )
        return override

    for pattern in _patterns():
        for path in sorted(glob.glob(pattern)):
            if _has_native_module(path):
                return path

    raise ImportError(
        "No %s found under SDK_pynaoqi/ (searched: %s).\n"
        "Platform: %s\n%s"
        % (
            _native_module_glob(),
            ", ".join(os.path.relpath(p, _ROOT) for p in _patterns()),
            sys.platform,
            _DOWNLOAD_HINT,
        )
    )


def add_sdk_to_path():
    """Make `qi` importable from either an extracted SDK or the active env."""
    try:
        lib = find_sdk_lib()
    except ImportError as sdk_error:
        # SoftBank also publishes a CPython 2.7 wheel for Windows.  When it is
        # installed in .venv-py2 no external SDK directory is necessary.
        try:
            import qi
        except ImportError:
            raise sdk_error
        return os.path.dirname(os.path.abspath(qi.__file__))

    if lib not in sys.path:
        sys.path.insert(0, lib)
    return lib


if __name__ == "__main__":
    print(add_sdk_to_path())
