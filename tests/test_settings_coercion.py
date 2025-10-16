from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dplus_sim import SettingsBridge, VelibSettingsAdapter  # noqa: E402


@pytest.mark.parametrize(
    "input_value, expected",
    [
        ("0", False),
        ("1", True),
        ("false", False),
        ("true", True),
        ("off", False),
        ("on", True),
        (" 0 ", False),
        ("FALSE", False),
        (0, False),
        (1, True),
    ],
)
@pytest.mark.parametrize("adapter", [SettingsBridge, VelibSettingsAdapter])
def test_boolean_coercion(adapter, input_value, expected):
    assert adapter._coerce_value("b", input_value) is expected
