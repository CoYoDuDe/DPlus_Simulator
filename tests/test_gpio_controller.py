import sys
from pathlib import Path
import unittest

# Sicherstellen, dass das src-Verzeichnis importiert werden kann
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

import dplus_sim  # noqa: E402


class FakeRPiGPIO:
    BCM = "BCM"
    OUT = "OUT"
    HIGH = 1
    LOW = 0

    def __init__(self) -> None:
        self.mode_calls: list[str] = []
        self.setup_calls: list[tuple[int, str]] = []
        self.output_calls: list[tuple[int, int]] = []
        self.cleanup_calls: list[int] = []
        self.levels: dict[int, int] = {}

    def setmode(self, mode: str) -> None:
        self.mode_calls.append(mode)

    def setup(self, pin: int, mode: str) -> None:
        self.setup_calls.append((pin, mode))

    def output(self, pin: int, level: int) -> None:
        self.output_calls.append((pin, level))
        self.levels[pin] = level

    def cleanup(self, pin: int) -> None:
        self.cleanup_calls.append(pin)


class GPIOControllerReconfigureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.original_gpio = dplus_sim._RPiGPIO
        self.fake_gpio = FakeRPiGPIO()
        dplus_sim._RPiGPIO = self.fake_gpio
        self.addCleanup(self._restore_gpio)

    def _restore_gpio(self) -> None:
        dplus_sim._RPiGPIO = self.original_gpio

    def test_reconfigure_preserves_output_state(self) -> None:
        controller = dplus_sim.GPIOController(pin=5, enabled=True)
        controller.write(True)
        self.assertEqual(controller.read(), True)
        self.assertIn((5, self.fake_gpio.OUT), self.fake_gpio.setup_calls)
        self.assertIn((5, self.fake_gpio.HIGH), self.fake_gpio.output_calls)

        controller.reconfigure(12)

        self.assertEqual(controller.pin, 12)
        self.assertEqual(controller.read(), True)
        self.assertIn(5, self.fake_gpio.cleanup_calls)
        self.assertIn((12, self.fake_gpio.OUT), self.fake_gpio.setup_calls)
        self.assertIn((12, self.fake_gpio.HIGH), self.fake_gpio.output_calls)

        controller.write(False)
        self.assertEqual(controller.read(), False)
        self.assertIn((12, self.fake_gpio.LOW), self.fake_gpio.output_calls)


if __name__ == "__main__":
    unittest.main()
