"""Tests für die Normalisierung von Relay-Kanälen."""

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dplus_sim import normalize_relay_channel  # noqa: E402


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Relays/4brelays/0", "4brelays/0"),
        ("Settings/Relays/relay/0/State", "0"),
        ("\\Relays\\Relay/1\\State", "1"),
        ("com.victronenergy.system/Relays/Relay/2", "2"),
    ],
)
def test_normalize_relay_channel(raw: str, expected: str) -> None:
    """Stellt sicher, dass verschiedene Präfixe entfernt werden."""

    assert normalize_relay_channel(raw) == expected
