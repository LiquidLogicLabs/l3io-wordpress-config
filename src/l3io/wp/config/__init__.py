"""
Read and write ``define()`` constants in a WordPress ``wp-config.php`` file.

A reader and writer for the ``define()`` subset of PHP that WordPress itself
writes -- not a PHP parser. ADR-0010 records the documented limits and the
read-back verification that guards them.
"""

from l3io.wp.config._version import __version__
from l3io.wp.config.adapters.config_file import WpConfigFile
from l3io.wp.config.core.config_string import WpConfigString
from l3io.wp.config.domain.errors import (
    ConfigKeyError,
    ConfigLookupError,
    ConfigReadError,
    ConfigValueError,
    ConfigWriteError,
    ReadBackError,
    WpConfigError,
)
from l3io.wp.config.domain.values import (
    MISSING,
    ConfigValue,
    EnvLookup,
    Expression,
    MissingType,
)

__all__ = [
    "__version__",
    "MISSING",
    "ConfigKeyError",
    "ConfigLookupError",
    "ConfigReadError",
    "ConfigValue",
    "ConfigValueError",
    "ConfigWriteError",
    "EnvLookup",
    "Expression",
    "MissingType",
    "ReadBackError",
    "WpConfigError",
    "WpConfigFile",
    "WpConfigString",
]
