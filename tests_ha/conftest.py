"""Home Assistant tests (need pytest-homeassistant-custom-component).

They are meant to run on Linux (CI). On Windows the asyncio event loop needs a
local socket pair, which the plugin's socket guard blocks; the guard is turned
off there.
"""

import sys

import pytest

if sys.platform == "win32":
    import pytest_socket

    pytest_socket.disable_socket = lambda *args, **kwargs: None

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow loading custom_components/growatt_web."""
    yield
