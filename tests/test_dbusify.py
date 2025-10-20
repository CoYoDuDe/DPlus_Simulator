"""Tests für die D-Bus-Serialisierung."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
from unittest.mock import Mock

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dplus_sim import DPlusSimService, Variant  # noqa: E402


class DummyController:
    """Minimaler Controller-Ersatz für die Tests."""

    def __init__(self, status: Dict[str, Any]) -> None:
        self._status = status

    async def start(self) -> None:  # pragma: no cover - für Schnittstellenkompatibilität
        return None

    async def stop(self) -> None:  # pragma: no cover - für Schnittstellenkompatibilität
        return None

    async def shutdown(self) -> None:  # pragma: no cover - für Schnittstellenkompatibilität
        return None

    async def update_settings(self, settings: Dict[str, Any]) -> Dict[str, Any]:  # pragma: no cover
        return settings

    async def inject_voltage(self, voltage: float) -> Dict[str, Any]:  # pragma: no cover
        return {"voltage": voltage}

    def get_settings(self) -> Dict[str, Any]:  # pragma: no cover
        return {}

    def get_status(self) -> Dict[str, Any]:
        return self._status


NESTED_STATUS: Dict[str, Any] = {
    "running": True,
    "ignition": {
        "enabled": True,
        "details": {
            "history": [
                {"state": False, "reasons": ("voltage", "unavailable")},
                {"state": True, "reasons": ["override", {"code": 5}]},
            ]
        },
    },
    "measurements": [
        {"voltage": 13.2, "valid": True},
        ("stale", {"age": 3}),
    ],
    "metadata": {
        "version": "1.0",
        "flags": [True, False, {"deep": "value"}],
    },
}


def _assert_variant_tree(data: Dict[str, Variant]) -> None:
    for key, variant in data.items():
        assert isinstance(key, str)
        assert isinstance(variant, Variant)
        _assert_variant_value(variant.value)


def _assert_variant_value(value: Any) -> None:
    if isinstance(value, dict):
        for nested_key, nested_variant in value.items():
            assert isinstance(nested_key, str)
            assert isinstance(nested_variant, Variant)
            _assert_variant_value(nested_variant.value)
    elif isinstance(value, list):
        for element in value:
            assert isinstance(element, Variant)
            _assert_variant_value(element.value)
    else:
        assert not isinstance(value, Variant)


def test_get_status_returns_recursive_variants() -> None:
    controller = DummyController(NESTED_STATUS)
    service = DPlusSimService(controller, lambda: None)

    result = service.GetStatus()

    _assert_variant_tree(result)


def test_status_changed_emits_recursive_variants() -> None:
    controller = DummyController(NESTED_STATUS)
    service = DPlusSimService(controller, lambda: None)
    handler = Mock()
    service.StatusChanged = handler  # type: ignore[assignment]

    service.emit_status(NESTED_STATUS)

    handler.assert_called_once()
    emitted_status = handler.call_args[0][0]
    _assert_variant_tree(emitted_status)
