"""Tests für rekursive Variant-Wandlung in DPlusSimService."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
from unittest.mock import Mock

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dplus_sim import DPlusSimService, Variant  # noqa: E402


class _DummyController:
    def __init__(self, status: Dict[str, Any]) -> None:
        self._status = status

    def get_status(self) -> Dict[str, Any]:
        return self._status

    async def start(self) -> None:  # pragma: no cover - Schnittstellenstub
        return None

    async def stop(self) -> None:  # pragma: no cover - Schnittstellenstub
        return None

    async def shutdown(self) -> None:  # pragma: no cover - Schnittstellenstub
        return None

    async def update_settings(self, settings: Dict[str, Any]) -> Dict[str, Any]:  # pragma: no cover
        return settings

    async def inject_voltage(self, voltage: float) -> Dict[str, Any]:  # pragma: no cover
        return {"voltage": voltage}

    def get_settings(self) -> Dict[str, Any]:  # pragma: no cover
        return {}


NESTED_STATUS: Dict[str, Any] = {
    "running": True,
    "ignition": {
        "enabled": True,
        "history": [
            {"state": False, "reasons": ("voltage", "manual")},
            {"state": True, "reasons": ["override", {"code": 5}]},
        ],
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


def _assert_recursive_variants(data: Dict[str, Variant]) -> None:
    for key, variant in data.items():
        assert isinstance(key, str)
        assert isinstance(variant, Variant)
        _assert_variant_payload(variant.value)


def _assert_variant_payload(payload: Any) -> None:
    if isinstance(payload, dict):
        for nested_key, nested_value in payload.items():
            assert isinstance(nested_key, str)
            assert isinstance(nested_value, Variant)
            _assert_variant_payload(nested_value.value)
    elif isinstance(payload, list):
        for element in payload:
            assert isinstance(element, Variant)
            _assert_variant_payload(element.value)
    else:
        assert not isinstance(payload, Variant)


def test_get_status_returns_variants_recursively() -> None:
    controller = _DummyController(NESTED_STATUS)
    service = DPlusSimService(controller, lambda: None)

    result = service.GetStatus()

    _assert_recursive_variants(result)


def test_status_changed_emits_recursive_variants() -> None:
    controller = _DummyController(NESTED_STATUS)
    service = DPlusSimService(controller, lambda: None)
    handler = Mock()
    service.StatusChanged = handler  # type: ignore[assignment]

    service.emit_status(NESTED_STATUS)

    handler.assert_called_once()
    emitted = handler.call_args.args[0]
    _assert_recursive_variants(emitted)
