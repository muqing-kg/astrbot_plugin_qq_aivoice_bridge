"""The plugin entry module must import with only the AstrBot API available."""

import sys
from pathlib import Path

from tests.astrbot_stub import install

install()

# The plugin package is imported by its distribution name, so its parent
# directory has to be importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def test_plugin_package_imports():
    import astrbot_plugin_qq_aivoice_bridge.main as plugin_main

    assert hasattr(plugin_main, "QQAIVoiceBridgePlugin")
