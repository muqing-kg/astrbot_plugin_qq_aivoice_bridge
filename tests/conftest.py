"""Install the AstrBot stub before test modules import plugin code.

Plugin modules bind ``astrbot.api`` at import time, so the stub has to exist
before collection reaches the test files that import ``core`` directly.
"""

from tests.astrbot_stub import install

install()
