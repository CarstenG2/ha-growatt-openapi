"""Load the integration modules as package ``gw`` without running its __init__.

The package __init__ imports Home Assistant, which is not installed in the
test environment. The client and source modules do not need it.
"""

import pathlib
import sys
import types

_PKG_DIR = pathlib.Path(__file__).parents[1] / "custom_components" / "growatt_web"

if "gw" not in sys.modules:
    _pkg = types.ModuleType("gw")
    _pkg.__path__ = [str(_PKG_DIR)]
    sys.modules["gw"] = _pkg
