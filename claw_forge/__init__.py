"""claw-forge: Multi-provider autonomous coding agent harness."""

from importlib.metadata import version as _pkg_version

try:
    __version__ = _pkg_version("claw-forge")
except Exception:  # package not installed (e.g. editable dev mode without install)
    __version__ = "0.4.1"
