"""Tests für SettingsBridge-Signalfilter."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

import dplus_sim  # noqa: E402
from dplus_sim import MessageType, SettingsBridge  # noqa: E402


class DummyBus:
    """Minimaler Testbus, der nur GetNameOwner beantwortet."""

    def __init__(self, owner: str) -> None:
        self.owner = owner
        self.calls = []

    async def call(self, message: Any) -> SimpleNamespace:  # type: ignore[override]
        self.calls.append(message)
        if getattr(message, "member", None) == "GetNameOwner":
            return SimpleNamespace(body=[self.owner])
        return SimpleNamespace(body=[])

    def add_message_handler(self, _handler):  # pragma: no cover - im Test nicht benötigt
        pass

    def remove_message_handler(self, _handler):  # pragma: no cover - im Test nicht benötigt
        pass


def test_settings_bridge_accepts_unique_sender() -> None:
    """Die SettingsBridge verarbeitet Signale von eindeutigen Sender-IDs."""

    async def _scenario() -> None:
        definitions = {
            "example": {
                "path": "/Example/Path",
                "type": "s",
                "default": "initial",
            }
        }
        updates: list[tuple[str, str]] = []

        def callback(key: str, value: str) -> None:
            updates.append((key, value))

        bus = DummyBus(":1.23")
        bridge = SettingsBridge(bus, definitions, callback=callback)
        bridge._loop = asyncio.get_running_loop()

        original_message = dplus_sim.Message

        class _FakeMessage:
            def __init__(
                self,
                *,
                destination: str,
                path: str,
                interface: str,
                member: str,
                signature: str,
                body: list[object],
            ) -> None:
                self.destination = destination
                self.path = path
                self.interface = interface
                self.member = member
                self.signature = signature
                self.body = body

        dplus_sim.Message = _FakeMessage
        try:
            await bridge._update_unique_sender()
        finally:
            dplus_sim.Message = original_message

        message = SimpleNamespace(
            message_type=getattr(MessageType, "SIGNAL", None),
            sender=":1.23",
            path="/Example/Path",
            member="PropertiesChanged",
            body=["com.victronenergy.BusItem", {"Value": "updated"}],
        )

        handled = bridge._handle_message(message)
        await asyncio.sleep(0)

        assert handled is True
        assert updates == [("example", "updated")]

    asyncio.run(_scenario())
