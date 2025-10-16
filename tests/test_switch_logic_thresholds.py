import asyncio
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dplus_sim import DPlusController  # noqa: E402


def test_effective_thresholds_equal_configured_values() -> None:
    controller = DPlusController(
        {
            "on_voltage": 3.35,
            "off_voltage": 3.25,
            "hysteresis": 0.1,
        },
        use_gpio=False,
    )

    try:
        status = controller.get_status()

        assert status["effective_on_voltage"] == pytest.approx(3.35)
        assert status["effective_off_voltage"] == pytest.approx(3.25)
    finally:
        asyncio.run(controller.shutdown())
